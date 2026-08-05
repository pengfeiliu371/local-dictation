# Local Dictation for Windows

一个本地运行的按住说话（push-to-talk）听写工具。按住全局热键说话、松开后，程序使用本机的 Qwen3-ASR 模型转写，并将最终文本粘贴到当前焦点所在的任意文本框：Codex、浏览器、终端、编辑器或聊天软件均可使用。

中文、英文及中英混杂场景是它的主要目标。音频和转写均在本机处理；首次安装时需要联网下载 Python 依赖和模型权重，日常听写不需要联网。

## 功能

- 全局按住说话：默认 `Right Ctrl`，松开后自动转写并粘贴。
- 系统托盘运行：启动后隐藏至 Windows 右下角；右键图标可查看设置或退出。
- 本地 GPU 听写：默认 `Qwen/Qwen3-ASR-1.7B`，更偏向准确性；可改用 `Qwen/Qwen3-ASR-0.6B` 以获得更低延迟。
- 可选去除中文、英文口语填充词，例如“嗯、呃、啊、um、uh”。
- 不自动按 Enter 或执行命令，粘贴后的发送或执行始终由使用者确认。

## 系统要求

- Windows 10 或 Windows 11。
- Python 3.12（安装时勾选 Python Launcher；PowerShell 中 `py -3.12 --version` 应能运行）。
- 建议配备 NVIDIA GPU 与可用 CUDA 驱动。默认 1.7B 模型适合显存较充足的设备；显存紧张时请使用 0.6B 模型。
- 可用的默认麦克风。首次安装还需要网络连接和若干 GB 磁盘空间。

目前的安装脚本会验证 CUDA，因此该开源版本优先支持 NVIDIA GPU。没有 NVIDIA GPU 的电脑可以自行安装 CPU 版 PyTorch 并调整代码配置，但速度会明显下降。

## 推荐硬件

下表按“听写程序单独运行”估计。实际显存还会受到显示器、浏览器、LM Studio、游戏和其他 AI 程序影响；若要同时运行其他本地模型，请为它们另行预留显存。

| 使用方式 | 可用下限 | 推荐配置 | 体验说明 |
| --- | --- | --- | --- |
| `Qwen3-ASR-0.6B` + GPU | NVIDIA GPU，8 GB 显存 | RTX 3060 12 GB、RTX 4060 Ti 16 GB 或更高 | 适合低延迟短句听写；8 GB 卡需关闭其他占显存较多的程序。 |
| `Qwen3-ASR-1.7B` + GPU | NVIDIA GPU，12 GB 显存 | 16 GB 显存或更高，例如 RTX 4060 Ti 16 GB、RTX 4070 Ti SUPER 16 GB、RTX 4080/4090 | 准确率及中英混杂表现更好；若同时开 LM Studio，建议 24 GB 以上或避免两者并行。 |
| CPU 模式（实验性） | 现代 6 核 CPU、16 GB 系统内存 | Ryzen 7 / Core i7 级别或更高的 8 核以上 CPU、32 GB 系统内存 | 可以使用，但通常比 GPU 慢得多，尤其是长句；适合没有 NVIDIA GPU 的临时方案。 |

对于大多数中文为主、偶尔中英混杂的日常输入：有 16 GB 显存时优先使用 1.7B；只有 8–12 GB 显存或更看重响应速度时使用 0.6B。模型加载后会保留显存以减少下一次听写的等待；退出程序才会释放这部分资源。

## 从零安装

1. 安装 [Python 3.12](https://www.python.org/downloads/)，然后重开 PowerShell。
2. 克隆本仓库并进入目录：

   ```powershell
   git clone https://github.com/pengfeiliu371/local-dictation.git
   cd local-dictation
   ```

3. 运行一次安装脚本。它会创建虚拟环境、安装 CUDA PyTorch 与依赖、下载默认模型：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   ```

4. 启动程序：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\run.ps1
   ```

5. 可选：创建桌面快捷方式：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install_shortcut.ps1
   ```

首次启动和模型下载会比之后慢。托盘图标就绪后，单击任意文本框，按住 `Right Ctrl` 说话，松开即可粘贴文字。

## 配置与模型

`setup.ps1` 会在首次运行时由 `config.example.json` 创建本机的 `config.json`。`config.json` 被 Git 忽略，适合保存你的设备和偏好；修改后重新启动程序。

常用配置：

| 字段 | 说明 |
| --- | --- |
| `hotkey` | 默认 `right_ctrl`；可用 `scroll_lock`、`pause` 或 `f1` 至 `f24`。 |
| `model_id` | 默认 `Qwen/Qwen3-ASR-1.7B`；低延迟可设为 `Qwen/Qwen3-ASR-0.6B`。 |
| `max_record_seconds` | 单次录音的最长秒数。 |
| `input_device` | `null` 表示使用 Windows 默认麦克风；可填 `sounddevice` 的设备编号。 |
| `clean_fillers` | `true` 时清除独立的口语填充词。 |
| `paste_delay_seconds` | 复制后、粘贴前的等待时间。个别应用粘贴不稳定时可略微增加。 |

若修改 `model_id`，运行 `download_model.ps1` 预下载新模型，或在联网状态下启动程序让它下载。模型文件保存在本机 `models/`，不会被提交到 GitHub。

## 常见问题

**按热键没有反应**：确认托盘图标已就绪、当前没有其他程序占用热键，并检查 `codex-ptt.log`。若目标程序以管理员身份运行，也请以管理员身份启动 Local Dictation。

**文本没有粘贴**：先确认焦点在普通文本框内。密码框及受保护的应用可能会阻止剪贴板或模拟按键。

**首次启动很慢或显存占用高**：这是模型载入到 GPU 的正常表现。模型常驻显存可换来之后更快的听写；退出程序后模型应释放。显存不足时改用 0.6B 模型。

**想换热键**：编辑 `config.json` 的 `hotkey` 后重启。避免使用单独的 Caps Lock，因为它会改变键盘状态。

## 隐私与安全

- 语音、转写和模型推理都在本机进行；本项目不提供云端转写服务。
- 程序只会粘贴转写文本，不会替你按 Enter、点击按钮或执行语音中的命令。
- 日志可能包含运行时间和诊断信息。若分享日志，请先检查其中内容。

## 开发与打包

`build_portable.ps1` 用于生成便携版，`installer.iss` 为 Inno Setup 安装包脚本。它们属于开发者工具，不是正常使用所必需。

## License

[MIT](LICENSE)
