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
    weight_suffixes = {".safetensors…5220 tokens truncated…    model_status.setText("Installed locally - model is loading.")
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
