# Local Dictation for Windows

Local Dictation is a push-to-talk dictation app that runs on your own Windows PC. Hold a global hotkey to speak; release it to transcribe with a local Qwen3-ASR model and paste the result into whichever text field has focus—Codex, a browser, a terminal, an editor, or a chat app.

It is designed primarily for Chinese, English, and natural Chinese-English code-switching dictation. The included Qwen3-ASR models are a particularly good fit for Mandarin speech that mixes English words, product names, technical terms, code, and abbreviations. Audio and inference remain local. Internet access is needed only for the first installation, when Python packages and model weights are downloaded.

## Features

- Global push-to-talk: hold `Right Ctrl` by default; release to transcribe and paste.
- System-tray operation: the app runs near the Windows clock; right-click its icon for settings or exit.
- Local GPU transcription: Qwen3-ASR is selected specifically for Chinese, English, and mixed Chinese-English speech. `Qwen/Qwen3-ASR-1.7B` is the default accuracy-oriented model; switch to `Qwen/Qwen3-ASR-0.6B` for lower latency.
- Optional removal of filler words such as “um”, “uh”, “嗯”, and “呃”.
- Safe output: the app pastes text only. It never presses Enter, clicks buttons, or executes dictated commands.

## Requirements

- Windows 10 or Windows 11.
- Python 3.12, installed with the Python Launcher enabled. `py -3.12 --version` should work in PowerShell.
- An NVIDIA GPU with a current CUDA-capable driver is strongly recommended.
- A working default microphone, an internet connection for first-time setup, and several GB of free disk space.

The included setup script validates CUDA and is therefore GPU-first. A CPU-only setup is possible with a CPU build of PyTorch and local adjustments, but it will be substantially slower.

## Recommended hardware

These estimates assume Local Dictation is the main GPU workload. Browsers, games, LM Studio, and other local AI tools consume additional VRAM, so leave headroom if they will run at the same time.

| Mode | Practical minimum | Recommended | Notes |
| --- | --- | --- | --- |
| `Qwen3-ASR-0.6B` on GPU | NVIDIA GPU with 8 GB VRAM | RTX 3060 12 GB, RTX 4060 Ti 16 GB, or better | Best for responsive short dictation. An 8 GB GPU may require closing other VRAM-heavy apps. |
| `Qwen3-ASR-1.7B` on GPU | NVIDIA GPU with 12 GB VRAM | 16 GB VRAM or more: RTX 4060 Ti 16 GB, RTX 4070 Ti SUPER 16 GB, RTX 4080/4090 | Better accuracy, particularly for mixed Chinese-English speech. If LM Studio is also active, 24 GB VRAM or avoiding concurrent model use is recommended. |
| CPU mode (experimental) | Modern 6-core CPU and 16 GB RAM | Ryzen 7 / Core i7 class or better, 8+ cores and 32 GB RAM | Usable, but typically much slower than GPU inference, especially for long speech. |

For everyday Chinese dictation with occasional English, use the 1.7B model when you have 16 GB VRAM. Use 0.6B if you have 8–12 GB VRAM or prioritize speed. A loaded model stays in VRAM to make later dictation faster; exit the app to release that memory.

## Installation from scratch

1. Install [Python 3.12](https://www.python.org/downloads/) and reopen PowerShell.
2. Clone this repository and enter its directory:

   ```powershell
   git clone https://github.com/pengfeiliu371/local-dictation.git
   cd local-dictation
   ```

3. Run the one-time setup. It creates a virtual environment, installs CUDA PyTorch and dependencies, and downloads the default model:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   ```

4. Start the app:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\run.ps1
   ```

5. Optionally create a Desktop shortcut:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install_shortcut.ps1
   ```

The first model download and launch take longer than subsequent launches. Once the tray icon is ready, focus any normal text field, hold `Right Ctrl` to speak, and release it to paste the transcription.

## Configuration and models

On its first run, `setup.ps1` creates a local `config.json` from `config.example.json`. `config.json` is ignored by Git, so it is safe for machine-specific preferences. Restart the app after changing it.

| Field | Purpose |
| --- | --- |
| `hotkey` | Defaults to `right_ctrl`; supported alternatives include `scroll_lock`, `pause`, and `f1` through `f24`. |
| `model_id` | Defaults to `Qwen/Qwen3-ASR-1.7B`; set `Qwen/Qwen3-ASR-0.6B` for lower latency. |
| `max_record_seconds` | Maximum duration of one recording. |
| `input_device` | `null` uses the Windows default microphone; set a `sounddevice` device number to select another microphone. |
| `clean_fillers` | When `true`, removes standalone conversational filler words. |
| `paste_delay_seconds` | Wait time between copying and pasting. Increase slightly if a particular app misses pastes. |

When changing `model_id`, run `download_model.ps1` to pre-download it, or launch while online and allow the app to download it. Model files are kept in the local `models/` folder and are never committed to GitHub.

## Troubleshooting

**The hotkey does nothing.** Confirm that the tray icon is ready, no other app owns the same hotkey, and inspect `codex-ptt.log`. If the target application is running as Administrator, run Local Dictation as Administrator too.

**Text is not pasted.** Make sure focus is in a normal editable field. Password fields and protected applications may block clipboard access or simulated keystrokes.

**The first launch is slow or VRAM use is high.** This is expected while loading a model to the GPU. Keeping it loaded makes future dictation fast. Switch to the 0.6B model if VRAM is limited.

**I want another hotkey.** Edit `hotkey` in `config.json` and restart. Avoid Caps Lock alone because it changes keyboard state.

## Privacy and safety

- Speech, transcription, and model inference remain on your computer; this project does not provide a cloud transcription service.
- The app only pastes transcribed text. You decide whether to send, submit, or execute it.
- Logs may include diagnostic information and timing. Review them before sharing.

## Development and packaging

`build_portable.ps1` builds a portable version. `installer.iss` is an Inno Setup installer script. They are developer tools and not required for ordinary use.

## License

[MIT](LICENSE)

