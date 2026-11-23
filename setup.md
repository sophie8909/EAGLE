# EAGLE Windows 安裝

## 執行步驟

1. 把含有 `setup.cmd` 的 EAGLE 原始碼搬到新電腦，讓腳本重建 `.venv`。若要用 Git 取得專案，先安裝 [Git for Windows 2.x x64](https://git-scm.com/download/win)，再 checkout 含有安裝腳本的版本。
2. 在 EAGLE 資料夾開 PowerShell，執行 `.\setup.cmd -WithEditor`。會裝 Python 相依套件、MicroRTS 和四個對手、llama.cpp、Qwen、VS Code 及 Python／Java 擴充套件。已有編輯器可直接執行 `.\setup.cmd`。
3. 執行 `.\gui.cmd`。開啟要跑的 YAML，將 `model.llama_server` 設為下方路徑並儲存。1111、1114 的 `model.path` 已對應腳本下載的位置。

```text
experiment_env/model/llama.cpp-b10236-win-cuda-12.4-x64/llama-server.exe
```

使用其他電腦的 LLM 服務時，改跑 `.\setup.cmd -ToolsOnly -WithEditor`，在 GUI 填入服務位址並勾選 Connect only。

## 更新已安裝的 MicroRTS

原始碼更新後，等現有實驗結束，再執行 `.\setup.cmd -ToolsOnly` 重編 MicroRTS。
新版在 `match_artifact_mode: compact` 下每場只用一個逐 tick 暫存檔。

## 額外下載或搬移

- Windows 10／11 x64 若缺 `winget`，安裝最新版 [Microsoft App Installer](https://apps.microsoft.com/detail/9nblggh4nns1)。
- 本機跑 Qwen 需要 NVIDIA GPU。先安裝顯卡對應的最新 Windows x64 驅動，須支援 CUDA 12.4。腳本會下載 CUDA DLL。[NVIDIA 驅動下載](https://www.nvidia.com/Download/index.aspx)
- 要保留舊實驗就搬 `runs/`。續跑前對照 Run 內 `config.yaml` 的絕對路徑。使用雲端模型才需要搬對應的 `api_key/` 檔案或重新登入。

## 腳本下載的版本

| 項目 | 版本和下載頁 |
| --- | --- |
| Python | 3.13 x64，已裝 3.12 可沿用。[Python for Windows](https://www.python.org/downloads/windows/) |
| Java | Temurin JDK 17 LTS x64。[Adoptium](https://adoptium.net/temurin/releases/?version=17) |
| llama.cpp | b10236 Windows x64 CUDA 12.4。[llama-server ZIP](https://github.com/ggml-org/llama.cpp/releases/download/b10236/llama-b10236-bin-win-cuda-12.4-x64.zip) · [CUDA DLL ZIP](https://github.com/ggml-org/llama.cpp/releases/download/b10236/cudart-llama-bin-win-cuda-12.4-x64.zip) · [VC++ v14 x64](https://aka.ms/vc14/vc_redist.x64.exe) |
| Qwen | Qwen3.5-9B UD-Q4_K_XL GGUF，約 5.97 GB。[Hugging Face](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/blob/24fadba/Qwen3.5-9B-UD-Q4_K_XL.gguf) |
| VS Code | Windows x64 Stable 和穩定版擴充套件。[VS Code](https://code.visualstudio.com/download) · [Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python) · [Extension Pack for Java](https://marketplace.visualstudio.com/items?itemName=vscjava.vscode-java-pack) |
