"""System-wide, local GPU push-to-talk dictation for Windows.

The recognizer is intentionally separate from Codex: it transcribes locally and
performs a normal Ctrl+V into whatever text field currently has focus. It never
presses Enter or otherwise submits a command.
"""

from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import tempfile
import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Any

import numpy as np
import pyperclip
import sounddevice as sd
from pynput import keyboard
from PySide6.QtCore import QProcess, QSettings, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QLabel,
    QMenu, QProgressBar, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget,
)

# Daily dictation must never wait on a network HEAD request. setup.ps1 performs
# the explicit one-time download; thereafter all model artifacts are local.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
APP_ICON_PATH = ROOT / "local-dictation.ico"

# All profiles use the same multilingual Qwen ASR family, so Chinese-English
# code switching remains available.  The smaller checkpoint is intentionally a
# separate option: it trades some accuracy for substantially lower VRAM/RAM.
MODEL_PROFILES: dict[str, dict[str, str]] = {
    "qwen_1_7b_gpu": {
        "label": "Accurate - Qwen 1.7B (GPU)",
        "model_id": "Qwen/Qwen3-ASR-1.7B",
        "device": "cuda",
        "description": "Best Chinese-English accuracy; about 4 GB+ of VRAM.",
    },
    "qwen_0_6b_gpu": {
        "label": "Fast / low VRAM - Qwen 0.6B (GPU)",
        "model_id": "Qwen/Qwen3-ASR-0.6B",
        "device": "cuda",
        "description": "Faster and lighter; slightly less accurate for difficult speech.",
        "template": "qwen_asr_chat_template.jinja",
    },
    "qwen_0_6b_cpu": {
        "label": "CPU compatible - Qwen 0.6B (CPU)",
        "model_id": "Qwen/Qwen3-ASR-0.6B",
        "device": "cpu",
        "description": "Works without an NVIDIA GPU, but is much slower.",
        "template": "qwen_asr_chat_template.jinja",
    },
}


def load_config() -> dict[str, Any]:
    with (ROOT / "config.json").open(encoding="utf-8") as handle:
        config = json.load(handle)
    settings = QSettings("Pengfei", "Local Dictation")
    if settings.contains("clean_fillers"):
        config["clean_fillers"] = settings.value("clean_fillers", type=bool)
    # Preserve existing installations' behavior after introducing profiles.
    config.setdefault("model_profile", "qwen_1_7b_gpu")
    return config


def save_config(config: dict[str, Any]) -> None:
    config_path = ROOT / "config.json"
    temporary_path = ROOT / "config.json.tmp"
    temporary_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(config_path)


def model_is_cached(model_id: str) -> bool:
    """Return true only when a downloaded snapshot contains model weights."""
    cache_root = Path(os.environ.get("HF_HUB_CACHE", Path.home() / ".cache" / "huggingface" / "hub"))
    snapshots = cache_root / f"models--{model_id.replace('/', '--')}" / "snapshots"
    if not snapshots.exists():
        return False
    weight_suffixes = {".safetensors", ".bin", ".pt", ".pth"}
    # Configuration/tokenizer files arrive first. They are not sufficient to
    # run ASR, so require at least one substantial weight file before calling a
    # model installed.
    return any(
        path.is_file() and path.suffix.lower() in weight_suffixes and path.stat().st_size > 100 * 1024 * 1024
        for path in snapshots.rglob("*")
    )


class DictationApp:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        # Settings may save a different profile before the process restarts.
        # Keep the actually loaded profile separate for accurate UI wording.
        self.active_model_profile = config.get("model_profile", "qwen_1_7b_gpu")
        self.audio_blocks: list[np.ndarray] = []
        self.recording = False
        self.finalizing_recording = False
        self.recording_started_at: float | None = None
        self.transcribing = False
        self.ready = False
        self.load_error: str | None = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        # Use the per-user temporary directory.  A project-folder log
        # can be left behind by an elevated launch with permissions that later
        # prevent ordinary desktop-shortcut launches from recording errors.
        log_directory = Path(tempfile.gettempdir()) / "LocalDictation"
        try:
            log_directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            log_directory = ROOT
        self.log_path = log_directory / "local-dictation.log"
        self.target_window = 0
        self.jobs: queue.Queue[np.ndarray | None] = queue.Queue()

        self.model: Any | None = None
        self.stream: sd.InputStream | None = None

    def initialize(self) -> None:
        """Load the GPU model in the background while the tray icon is visible."""
        # These imports are intentionally delayed: importing CUDA PyTorch and
        # Qwen takes several seconds on Windows, but the tray shell should be
        # visible immediately after a desktop-shortcut launch.
        import torch
        from qwen_asr import Qwen3ASRModel

        profile = MODEL_PROFILES.get(self.config.get("model_profile", ""), MODEL_PROFILES["qwen_1_7b_gpu"])
        use_gpu = profile["device"] == "cuda"
        if use_gpu and not torch.cuda.is_available():
            self.load_error = "The selected GPU model cannot find an NVIDIA CUDA GPU. Choose the CPU profile in Settings."
            self._log(self.load_error)
            return

        device_description = torch.cuda.get_device_name(0) if use_gpu else "CPU (slow mode)"
        self._log(f"Loading {profile['model_id']} on {device_description} ...")
        # language=None is deliberate: it preserves Chinese-English code switching
        # better than forcing the whole utterance into a single language.
        self.model = Qwen3ASRModel.from_pretrained(
            profile["model_id"],
            dtype=torch.bfloat16 if use_gpu else torch.float32,
            device_map="cuda:0" if use_gpu else "cpu",
            max_new_tokens=self.config.get("max_new_tokens", 1024),
            # The packaged application may need to fetch the model on a new
            # machine. The source version remains deliberately offline.
            local_files_only=self.config.get("local_files_only", True) and not getattr(sys, "frozen", False),
        )
        template_name = profile.get("template")
        if template_name and not getattr(self.model.processor, "chat_template", None):
            # The original 0.6B checkpoint is otherwise fully compatible but
            # omits this processor resource.  Supply the official template so
            # Qwen-ASR can build its audio transcription prompt.
            self.model.processor.chat_template = (ROOT / template_name).read_text(encoding="utf-8")

        # Many Windows microphones reject a 16 kHz capture request. Capture at
        # the device's native rate and resample each utterance to the ASR rate.
        self.input_device = self.config.get("input_device")
        device_info = sd.query_devices(self.input_device, kind="input")
        self.capture_sample_rate = int(round(device_info["default_samplerate"]))
        self._log(f"Microphone: {device_info['name']} ({self.capture_sample_rate} Hz)")
        self.stream = sd.InputStream(
            device=self.input_device,
            samplerate=self.capture_sample_rate,
            channels=1,
            dtype="float32",
            callback=self._audio_callback,
        )
        self.stream.start()
        self.ready = True
        self._log(f"Ready. Focus any text box, hold {self.config['hotkey']}, speak, then release it.")
        threading.Thread(target=self._transcription_worker, daemon=True).start()

    def _audio_callback(self, data: np.ndarray, _frames: int, _time: Any, status: sd.CallbackFlags) -> None:
        if status:
            self._log(f"Audio warning: {status}")
        with self.lock:
            if self.recording:
                self.audio_blocks.append(data.copy())

    def start_recording(self) -> None:
        with self.lock:
            if not self.ready or self.recording or self.finalizing_recording or self.transcribing:
                return
            self.audio_blocks.clear()
            self.recording = True
            self.recording_started_at = time.perf_counter()
        self._log("[listening]")

    def stop_recording(self) -> None:
        with self.lock:
            if not self.recording or self.finalizing_recording:
                return
            # Keep recording briefly after the key is released. Sounddevice
            # callbacks can still contain the final syllable at that moment.
            self.finalizing_recording = True

        tail_seconds = self.config.get("release_tail_seconds", 0.30)
        if tail_seconds > 0:
            time.sleep(tail_seconds)

        with self.lock:
            self.recording = False
            self.finalizing_recording = False
            self.recording_started_at = None
            audio = np.concatenate(self.audio_blocks, axis=0).reshape(-1) if self.audio_blocks else np.array([], dtype=np.float32)
            self.audio_blocks.clear()

        duration = len(audio) / self.capture_sample_rate
        if duration < self.config["minimum_audio_seconds"]:
            self._log("Ignored: recording was too short.")
            return
        if duration > self.config["max_record_seconds"]:
            self._log(f"Recording capped at {self.config['max_record_seconds']} seconds.")
            audio = audio[: int(self.config["max_record_seconds"] * self.capture_sample_rate)]
        audio = self._resample_to_asr_rate(audio)
        self.jobs.put(audio)

    def recording_seconds(self) -> float:
        with self.lock:
            if not self.recording or self.recording_started_at is None:
                return 0.0
            return time.perf_counter() - self.recording_started_at

    def _resample_to_asr_rate(self, audio: np.ndarray) -> np.ndarray:
        target_rate = self.config["sample_rate"]
        if self.capture_sample_rate == target_rate:
            return audio
        source_positions = np.arange(len(audio), dtype=np.float64)
        target_length = round(len(audio) * target_rate / self.capture_sample_rate)
        target_positions = np.linspace(0, len(audio) - 1, target_length)
        return np.interp(target_positions, source_positions, audio).astype(np.float32)

    def _clean_dictation(self, text: str) -> str:
        """Remove standalone hesitation sounds without rewriting task content."""
        if not self.config.get("clean_fillers", True):
            return text

        # Restrict matches to separate speech fragments. Words such as "就是"
        # and "然后" are intentionally preserved because they may be meaningful.
        filler = r"(?:嗯+|呃+|额+|啊+|唔+|噢+|哦+|um+|uh+|erm+)"
        boundary = r"(?=[\s,，。！？；!?;]|$)"
        # Consume the comma-like separator next to a removed filler as well.
        # Otherwise "嗯，帮我…" becomes the dangling "，帮我…".
        for _ in range(4):  # Handles consecutive fillers such as "呃，啊，…".
            cleaned = re.sub(
                rf"(^|[\s,，、;；]){filler}{boundary}[\s,，、;；]*",
                r"\1",
                text,
                flags=re.IGNORECASE,
            )
            if cleaned == text:
                break
            text = cleaned
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"([,，。！？；!?;])(?:\s*\1)+", r"\1", text)
        text = re.sub(r"^[\s,，、;；]+", "", text)
        text = re.sub(r"([。！？!?])\s*[,，、;；]+", r"\1", text)
        text = re.sub(r"[,，、;；]+\s*([。！？!?])", r"\1", text)
        text = re.sub(r"[,，、;；]+$", "", text)
        text = re.sub(r"\s+([,，。！？；!?;])", r"\1", text)
        return text.strip()

    def _transcription_worker(self) -> None:
        while True:
            audio = self.jobs.get()
            if audio is None:
                return
            with self.lock:
                self.transcribing = True
            try:
                started = time.perf_counter()
                self._log("Transcribing locally on GPU...")
                if self.model is None:
                    raise RuntimeError("ASR model is not ready.")
                result = self.model.transcribe(audio=(audio, self.config["sample_rate"]), language=None)
                asr_elapsed = time.perf_counter() - started
                text = result[0].text.strip() if result else ""
                cleanup_started = time.perf_counter()
                text = self._clean_dictation(text)
                cleanup_elapsed = time.perf_counter() - cleanup_started
                if text:
                    paste_started = time.perf_counter()
                    self._paste(text)
                    paste_elapsed = time.perf_counter() - paste_started
                    self._log(
                        f"[pasted in {time.perf_counter() - started:.2f}s; "
                        f"ASR {asr_elapsed:.2f}s, cleanup {cleanup_elapsed * 1000:.1f}ms, "
                        f"paste {paste_elapsed:.2f}s] {text}"
                    )
                else:
                    self._log("No speech recognized.")
            except Exception as error:  # Keep the hotkey listener alive after a failed utterance.
                self._log(f"Transcription failed: {error}")
            finally:
                with self.lock:
                    self.transcribing = False

    def _paste(self, text: str) -> None:
        old_clipboard: str | None = None
        if self.config["restore_clipboard_after_paste"]:
            try:
                old_clipboard = pyperclip.paste()
            except pyperclip.PyperclipException:
                pass

        pyperclip.copy(text)
        if self.target_window:
            ctypes.windll.user32.SetForegroundWindow(self.target_window)
            time.sleep(0.08)
        time.sleep(self.config["paste_delay_seconds"])
        controller = keyboard.Controller()
        with controller.pressed(keyboard.Key.ctrl):
            controller.press("v")
            controller.release("v")
        # Do not restore immediately: some apps read clipboard asynchronously.
        if old_clipboard is not None:
            time.sleep(0.25)
            pyperclip.copy(old_clipboard)

    def _log(self, message: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {message}"
        # Desktop shortcuts launch with a hidden console.  On some Windows
        # builds its stdout handle is invalid, so an unguarded print here can
        # terminate the background model-initialization thread before the tray
        # icon becomes ready.
        try:
            print(line, flush=True)
        except (OSError, AttributeError):
            pass
        try:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as error:
            # Logging must never prevent dictation from starting (for example,
            # after a previous elevated launch created a protected log file).
            try:
                print(f"Log write skipped: {error}", file=sys.stderr, flush=True)
            except (OSError, AttributeError):
                pass

    def close(self) -> None:
        self.stop_event.set()
        self.jobs.put(None)
        if self.stream:
            self.stream.stop()
            self.stream.close()


class TrayController:
    """Minimal Windows tray UI with a non-activating listening indicator."""

    def __init__(self, app: DictationApp) -> None:
        self.app = app
        self.qt_app = QApplication.instance() or QApplication(sys.argv)
        self.qt_app.setQuitOnLastWindowClosed(False)
        self.tray = QSystemTrayIcon(QIcon(str(APP_ICON_PATH)) if APP_ICON_PATH.exists() else self._mic_icon("#2f80ed"), self.qt_app)
        self.tray.setToolTip("Local Dictation — hold Right Ctrl to talk")
        # Keep Python references to the menu and actions.  A menu stored only
        # in a local variable can be garbage-collected by PySide on some
        # Windows builds, leaving a visible tray icon with no context menu.
        # QMenu only accepts a QWidget parent; QApplication is not one.  The
        # controller's self.menu reference below keeps the menu alive.
        self.menu = QMenu()
        self.status_action = QAction("Ready — hold Right Ctrl to talk", self.menu)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)
        self.settings_action = QAction("Settings…", self.menu)
        self.settings_action.triggered.connect(self._open_settings)
        self.menu.addAction(self.settings_action)
        self.menu.addSeparator()
        self.exit_action = QAction("Exit", self.menu)
        self.exit_action.triggered.connect(self._exit)
        self.menu.addAction(self.exit_action)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._handle_tray_activation)
        self.tray.show()
        # Explorer occasionally misses a tray registration during desktop
        # startup. Reassert visibility after the Qt event loop has started and
        # record whether Windows assigned an icon rectangle.
        QTimer.singleShot(1500, self._ensure_tray_visible)

        self.indicator = QWidget()
        self.indicator.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.indicator.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.indicator.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        card = QFrame(self.indicator)
        card.setStyleSheet(
            "QFrame { background: rgba(28, 32, 40, 235); border: 1px solid #4d5968; border-radius: 16px; }"
            "QLabel { color: white; font-family: 'Segoe UI'; }"
        )
        self.indicator_card = card
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 14, 22, 16)
        self.indicator_icon = QLabel("🎙")
        self.indicator_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.indicator_icon.setStyleSheet("font-size: 31px; color: #ff5a5f;")
        self.indicator_text = QLabel("Listening…")
        self.indicator_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.indicator_text.setStyleSheet("font-size: 13px; font-weight: 600;")
        layout.addWidget(self.indicator_icon)
        layout.addWidget(self.indicator_text)
        root_layout = QVBoxLayout(self.indicator)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(card)
        self.indicator.resize(164, 110)

        self.last_state = "idle"
        self.last_text = ""
        self.ready_notification_sent = False
        self.error_notification_sent = False
        self.model_download_process: QProcess | None = None
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._sync_status)
        self.status_timer.start(80)

    @staticmethod
    def _mic_icon(color: str) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(6, 6, 52, 52)
        painter.setBrush(QColor("white"))
        painter.drawRoundedRect(27, 16, 10, 22, 5, 5)
        painter.drawRoundedRect(21, 23, 22, 22, 10, 10)
        painter.drawRect(30, 43, 4, 8)
        painter.drawRoundedRect(23, 50, 18, 4, 2, 2)
        painter.end()
        return QIcon(pixmap)

    def _sync_status(self) -> None:
        if self.app.load_error:
            state, text, color = "error", "Local Dictation failed to start", "#e74c3c"
        elif not self.app.ready:
            profile = MODEL_PROFILES.get(self.app.active_model_profile, MODEL_PROFILES["qwen_1_7b_gpu"])
            device_name = "GPU" if profile["device"] == "cuda" else "CPU"
            state, text, color = "loading", f"Loading local {device_name} model…", "#7f8c8d"
        elif self.app.recording:
            remaining = max(0, self.app.config["max_record_seconds"] - self.app.recording_seconds())
            warning_seconds = self.app.config.get("recording_warning_seconds", 10)
            if remaining <= warning_seconds:
                state, text, color = "listening_warning", f"Listening… {max(0, int(remaining + 0.999))} seconds left", "#e74c3c"
            else:
                state, text, color = "listening", "Listening…", "#2f80ed"
        elif self.app.transcribing:
            state, text, color = "working", "Transcribing locally…", "#f39c12"
        else:
            state, text, color = "idle", "Ready — hold Right Ctrl to talk", "#2f80ed"
        if state == self.last_state and text == self.last_text:
            return
        self.last_state = state
        self.last_text = text
        self.tray.setIcon(self._mic_icon(color))
        self.status_action.setText(text)
        if state in ("idle", "loading", "error"):
            self.indicator.hide()
        else:
            self.indicator_text.setText(text)
            self.indicator_card.setStyleSheet(
                "QFrame { background: rgba(28, 32, 40, 235); "
                f"border: 2px solid {color}; border-radius: 16px; }}"
                "QLabel { color: white; font-family: 'Segoe UI'; }"
            )
            self.indicator.move(self.qt_app.primaryScreen().availableGeometry().center() - self.indicator.rect().center())
            self.indicator.show()
        if state == "idle" and not self.ready_notification_sent:
            self.ready_notification_sent = True
            self.tray.showMessage(
                "Local Dictation is ready",
                "Hold Right Ctrl to dictate.",
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
        elif state == "error" and not self.error_notification_sent:
            self.error_notification_sent = True
            self.tray.showMessage(
                "Local Dictation could not start",
                self.app.load_error or "Check the selected model in Settings.",
                QSystemTrayIcon.MessageIcon.Warning,
                7000,
            )

    def _ensure_tray_visible(self) -> None:
        self.tray.setVisible(True)
        geometry = self.tray.geometry()
        has_geometry = geometry.width() > 0 and geometry.height() > 0
        self.app._log(
            "Tray icon registered: "
            f"visible={self.tray.isVisible()}, "
            f"available={QSystemTrayIcon.isSystemTrayAvailable()}, "
            f"geometry={geometry.x()},{geometry.y()},{geometry.width()}x{geometry.height()}"
        )
        if has_geometry:
            return

        if os.environ.get("CODEX_SESSION_ID") or os.environ.get("CODEX_CI"):
            self.app._log(
                "No interactive tray was assigned in the Codex background session; "
                "exiting so the Desktop shortcut is not blocked."
            )
            self._exit()
            return

        # Explorer may still be starting or may just have restarted. Retry in
        # normal interactive sessions without terminating a valid dictation
        # process whose icon Windows placed in the overflow area.
        QTimer.singleShot(3000, lambda: self.tray.setVisible(True))

    def _exit(self) -> None:
        self.app.stop_event.set()
        self.tray.hide()
        self.qt_app.quit()

    def _handle_tray_activation(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # A double-click gives users an additional reliable way to reach
        # Settings, including when Windows shell extensions interfere with
        # a right-click on the notification-area icon.
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._open_settings()

    def _open_settings(self) -> None:
        dialog = QDialog()
        dialog.setWindowTitle("Local Dictation Settings")
        dialog.setModal(True)
        dialog.setFixedWidth(390)
        layout = QVBoxLayout(dialog)
        model_label = QLabel("Recognition model")
        layout.addWidget(model_label)
        model_profile = QComboBox()
        for profile_id, profile in MODEL_PROFILES.items():
            model_profile.addItem(profile["label"], profile_id)
        current_profile = self.app.config.get("model_profile", "qwen_1_7b_gpu")
        current_index = model_profile.findData(current_profile)
        model_profile.setCurrentIndex(max(0, current_index))
        layout.addWidget(model_profile)
        model_hint = QLabel()
        model_hint.setWordWrap(True)
        model_hint.setStyleSheet("color: #5f6368; font-size: 11px;")
        model_status = QLabel()
        model_status.setWordWrap(True)
        download_button = QPushButton("Download selected model")
        download_progress = QProgressBar()
        download_progress.setRange(0, 100)
        download_progress.setValue(0)
        download_progress.setVisible(False)
        restart_button = QPushButton("Restart now")
        restart_button.setToolTip("Save these settings and restart Local Dictation.")

        def refresh_model_hint(index: int) -> None:
            profile_id = model_profile.itemData(index)
            profile = MODEL_PROFILES[profile_id]
            installed = model_is_cached(profile["model_id"])
            model_hint.setText(profile["description"])
            if self.model_download_process and self.model_download_process.state() != QProcess.ProcessState.NotRunning:
                return
            if installed:
                if profile_id == self.app.active_model_profile and self.app.ready:
                    model_status.setText("Active now.")
                elif profile_id == self.app.active_model_profile:
                    model_status.setText("Installed locally - model is loading.")
                else:
                    model_status.setText("Installed locally - click Restart now to switch to it.")
                model_status.setStyleSheet("color: #27803c; font-size: 11px;")
                download_button.setEnabled(False)
                download_button.setText("Model already downloaded")
            else:
                model_status.setText("Not downloaded yet. Download once before selecting this model.")
                model_status.setStyleSheet("color: #b26a00; font-size: 11px;")
                download_button.setEnabled(True)
                download_button.setText("Download selected model")

        model_profile.currentIndexChanged.connect(refresh_model_hint)
        refresh_model_hint(model_profile.currentIndex())
        layout.addWidget(model_hint)
        layout.addWidget(model_status)
        layout.addWidget(download_button)
        layout.addWidget(download_progress)
        layout.addWidget(restart_button)

        def download_selected_model() -> None:
            if self.model_download_process and self.model_download_process.state() != QProcess.ProcessState.NotRunning:
                return
            profile_id = model_profile.currentData()
            model_profile.setEnabled(False)
            download_button.setEnabled(False)
            restart_button.setEnabled(False)
            download_button.setText("Downloading model…")
            download_progress.setValue(0)
            download_progress.setVisible(True)
            model_status.setText("Downloading in the background. This can take a few minutes.")
            model_status.setStyleSheet("color: #2f80ed; font-size: 11px;")
            # The downloader belongs to the application, not this dialog: the
            # user can close Settings and keep dictating with the current model.
            process = QProcess(self.qt_app)
            process.setProgram("powershell.exe")
            process.setArguments([
                "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(ROOT / "download_model.ps1"), "-Profile", profile_id,
            ])
            progress = {"total": 0, "downloaded": 0, "remainder": ""}

            def update_download_progress() -> None:
                output = bytes(process.readAllStandardOutput()).decode(errors="replace")
                output += bytes(process.readAllStandardError()).decode(errors="replace")
                progress["remainder"] += output.replace("\r", "\n")
                lines = progress["remainder"].split("\n")
                progress["remainder"] = lines.pop()
                for line in lines:
                    total_match = re.search(r"TOTAL_BYTES=(\d+)", line)
                    bytes_match = re.search(r"PROGRESS_BYTES=(\d+)", line)
                    if total_match:
                        progress["total"] = int(total_match.group(1))
                    if bytes_match:
                        progress["downloaded"] = int(bytes_match.group(1))
                if progress["total"]:
                    percentage = min(100, round(progress["downloaded"] * 100 / progress["total"]))
                    download_progress.setValue(percentage)
                    downloaded_gb = progress["downloaded"] / 1024 ** 3
                    total_gb = progress["total"] / 1024 ** 3
                    model_status.setText(f"Downloading in the background… {percentage}% ({downloaded_gb:.2f} / {total_gb:.2f} GB)")

            def download_finished(exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
                model_profile.setEnabled(True)
                restart_button.setEnabled(True)
                download_progress.setVisible(False)
                if exit_code == 0 and model_is_cached(MODEL_PROFILES[profile_id]["model_id"]):
                    model_status.setText("Download complete. Save the selection, then restart Local Dictation.")
                    model_status.setStyleSheet("color: #27803c; font-size: 11px;")
                    download_button.setText("Model downloaded")
                    self.tray.showMessage(
                        "Model download complete",
                        "Open Settings to select it, then click Restart now.",
                        QSystemTrayIcon.MessageIcon.Information,
                        5000,
                    )
                else:
                    model_status.setText("Download failed. Check your internet connection and try again.")
                    model_status.setStyleSheet("color: #c0392b; font-size: 11px;")
                    download_button.setEnabled(True)
                    download_button.setText("Try download again")
                    self.tray.showMessage(
                        "Model download failed",
                        "Check the internet connection and try again from Settings.",
                        QSystemTrayIcon.MessageIcon.Warning,
                        5000,
                    )

            process.finished.connect(download_finished)
            process.readyReadStandardOutput.connect(update_download_progress)
            process.readyReadStandardError.connect(update_download_progress)
            self.model_download_process = process
            process.start()
            self.tray.showMessage(
                "Downloading model",
                "Your current dictation model remains available while this downloads.",
                QSystemTrayIcon.MessageIcon.Information,
                3500,
            )

        download_button.clicked.connect(download_selected_model)
        recording_limit_label = QLabel("Maximum recording length")
        layout.addWidget(recording_limit_label)
        recording_limit = QComboBox()
        for seconds in (30, 45, 60):
            recording_limit.addItem(f"{seconds} seconds", seconds)
        current_limit = int(self.app.config.get("max_record_seconds", 45))
        limit_index = recording_limit.findData(current_limit)
        if limit_index < 0:
            recording_limit.addItem(f"{current_limit} seconds", current_limit)
            limit_index = recording_limit.count() - 1
        recording_limit.setCurrentIndex(limit_index)
        layout.addWidget(recording_limit)
        clean_fillers = QCheckBox("Remove fillers (嗯、呃、啊、um, uh)")
        clean_fillers.setChecked(self.app.config.get("clean_fillers", True))
        layout.addWidget(clean_fillers)
        hint = QLabel("Only standalone hesitation sounds are removed; task wording, code, and file names are kept.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5f6368; font-size: 11px;")
        layout.addWidget(hint)

        def save_current_settings() -> bool:
            selected_profile = model_profile.currentData()
            model_changed = selected_profile != current_profile
            self.app.config["model_profile"] = selected_profile
            # Kept for backward compatibility with existing config files and
            # scripts that read model_id directly.
            self.app.config["model_id"] = MODEL_PROFILES[selected_profile]["model_id"]
            self.app.config["max_record_seconds"] = int(recording_limit.currentData())
            self.app.config["clean_fillers"] = clean_fillers.isChecked()
            save_config(self.app.config)
            QSettings("Pengfei", "Local Dictation").setValue("clean_fillers", clean_fillers.isChecked())
            return model_changed

        restarting = False

        def restart_now() -> None:
            nonlocal restarting
            if self.model_download_process and self.model_download_process.state() != QProcess.ProcessState.NotRunning:
                return
            save_current_settings()
            # The delayed launcher waits for this process to release its Windows
            # single-instance mutex before starting the replacement process.
            launcher = str(ROOT / "start_tray.ps1").replace("'", "''")
            QProcess.startDetached(
                "powershell.exe",
                [
                    "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                    f"Start-Sleep -Milliseconds 700; & '{launcher}'",
                ],
            )
            restarting = True
            dialog.accept()
            self._exit()

        restart_button.clicked.connect(restart_now)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            model_changed = save_current_settings()
            if restarting:
                return
            status = "enabled" if clean_fillers.isChecked() else "disabled"
            message = f"Filler removal {status}."
            if model_changed:
                message += " Model saved; exit and reopen Local Dictation to apply it."
            self.tray.showMessage("Settings saved", message, QSystemTrayIcon.MessageIcon.Information, 5000)

    def run(self) -> None:
        self.qt_app.exec()


def main() -> None:
    mutex_name = "Local\\PengfeiLocalDictation"
    mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    if not mutex_handle:
        raise RuntimeError("Could not create the Local Dictation single-instance lock.")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print("Local Dictation is already running.", flush=True)
        return

    config = load_config()
    app = DictationApp(config)
    controller: TrayController | None = None
    if config.get("input_mode") == "tray":
        controller = TrayController(app)

    # The visible shell appears first; loading the 1.7B model proceeds in the
    # background so desktop startup never feels frozen.
    def background_initialize() -> None:
        try:
            app.initialize()
        except Exception as error:
            app.load_error = str(error)
            app._log(f"Startup failed: {error}")

    threading.Thread(target=background_initialize, daemon=True).start()

    virtual_keys = {f"f{number}": 0x6F + number for number in range(1, 25)}
    virtual_keys.update({
        "right_ctrl": 0xA3,
        "scroll_lock": 0x91,
        "pause": 0x13,
    })
    hotkey = config["hotkey"].lower()
    if hotkey not in virtual_keys:
        raise ValueError("Use F1-F24, right_ctrl, scroll_lock, or pause as the push-to-talk hotkey.")
    push_to_talk_vk = virtual_keys[hotkey]
    user32 = ctypes.windll.user32

    def key_is_down(virtual_key: int) -> bool:
        return bool(user32.GetAsyncKeyState(virtual_key) & 0x8000)

    def native_key_loop() -> None:
        was_down = False
        app._log(f"Windows native key monitor active for {hotkey}.")
        while not app.stop_event.is_set():
            is_down = key_is_down(push_to_talk_vk)
            if is_down and not was_down:
                app.start_recording()
            elif was_down and not is_down:
                app.stop_recording()
            was_down = is_down
            if key_is_down(0x11) and key_is_down(0x12) and key_is_down(ord("Q")):
                app._log("Quit hotkey received.")
                app.stop_event.set()
            time.sleep(0.01)

    threading.Thread(target=native_key_loop, daemon=True).start()

    def registered_hotkey_loop() -> None:
        # RegisterHotKey is the Windows shell's global-hotkey mechanism. It is
        # independent of Python event hooks and works while another app has focus.
        WM_HOTKEY = 0x0312
        PM_REMOVE = 0x0001
        MOD_NOREPEAT = 0x4000
        hotkey_id = 7319
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
        if not user32.RegisterHotKey(None, hotkey_id, MOD_NOREPEAT, push_to_talk_vk):
            app._log(f"RegisterHotKey failed for {hotkey}; another app may own it.")
            return
        app._log(f"Windows RegisterHotKey active for {hotkey}.")
        try:
            while not app.stop_event.is_set():
                while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, PM_REMOVE):
                    if message.message == WM_HOTKEY and message.wParam == hotkey_id:
                        app.start_recording()
                        while key_is_down(push_to_talk_vk) and not app.stop_event.is_set():
                            time.sleep(0.01)
                        app.stop_recording()
                time.sleep(0.01)
        finally:
            user32.UnregisterHotKey(None, hotkey_id)

    threading.Thread(target=registered_hotkey_loop, daemon=True).start()

    try:
        if controller:
            controller.run()
        else:
            app.stop_event.wait()
    except KeyboardInterrupt:
        print("\nStopping...", flush=True)
    finally:
        app.close()
        ctypes.windll.kernel32.CloseHandle(mutex_handle)


if __name__ == "__main__":
    main()
