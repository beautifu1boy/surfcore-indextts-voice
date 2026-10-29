# Changelog

## 0.1.0 — 2026-10-29

首个可用版本。在 Windows 11 + Ryzen 5 5600X + RX 6750 GRE 12G（ZLUDA）+
IndexTTS2 Windows 整合包上实测跑通 QQ 语音收发。

### 新增

- `bridge/server.py`：SurfCore `/v1/speak/file` 契约兼容层
  - 三种后端：`http`（对接整合包/任意 OpenAI 式 TTS）、`indextts`（官方仓库直调）、`mock`（链路自检）
  - 同时支持 voxd 插件引擎契约 `POST /say`
  - 试音台（浏览器 `/`）
- `pack/`：占位语音包，让 SurfCore 设置页「语音 → 启动」可用
  - `launcher.py`：端口探测（避免重复加载模型）、HF 离线环境、`CREATE_NO_WINDOW` 静默启动
  - `run.bat` / `gsv.bat` / `stop.bat` / `status.bat`
- `scripts/install.ps1`：一键安装（幂等），自动修 HuggingFace 缓存的 `campplus` 指针、
  建 `.venv\Scripts` junction、打开 SurfCore 的三个语音开关
- `scripts/verify.ps1`：链路体检（不发 QQ 消息，用 `curl --noproxy` 绕系统代理）
- `scripts/probe-tools.mjs`：跟 MCP server 握手，打印真实工具表 + 磁盘上的三个语音开关
- `scripts/uninstall.ps1`：卸载（保留模型与参考音频）
- 文档：安装、排错（6 个真机坑）、A 卡/ZLUDA 说明、配置手册

### 修复的真问题（写在这里免得后人再踩）

1. 整合包 `api.py` 启动时 `hf_hub_download("funasr/campplus")` 因 Xet 存储超时而整进程退出；
   并且自带缓存的 `refs/main` 指向空快照 → 强制离线 + 重指 `refs/main`。
2. 系统代理会劫持 `127.0.0.1` 的 Python 请求并返回 502 → 兼容层所有出站请求 `ProxyHandler({})`。
3. `pythonw` 下 `sys.stdout` 不可用，`print()` 在请求路径上抛异常导致 connection reset → `log()` 全包。
4. SurfCore 的 `spawn(cmd,{detached:true})` 在 Windows 会新开控制台 → 启动逻辑挪进 Python，
   用 `DETACHED_PROCESS | CREATE_NO_WINDOW`。
5. `socialV2.voice.enabled` 与 `socialV2.voice.tts.enabled` 是两个开关，前者为 false 时
   MCP 根本不注册 `qq_send_voice`（操作者通道却仍可用，容易误判"服务没问题"）。

### 已知问题

- 首次推理要付一次 ZLUDA 内核编译（实测约 50 分钟），目前没找到落盘缓存。
- 推理期间 uvicorn 事件循环被阻塞，`/health` 也会超时（属正常）。
- ZLUDA 路径 RTF 约 12~20，不适合长句。
