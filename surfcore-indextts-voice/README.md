# surfcore-indextts-voice

给 [SurfCore](https://github.com/Mieksido/surfcore) 换一个**不吃 N 卡**的语音引擎：用
[IndexTTS2](https://github.com/index-tts/index-tts) 顶掉原来的 `voxd + GPT-SoVITS(CUDA)`，
让 QQ 里的声音在 **AMD 显卡**（通过 ZLUDA）或纯 CPU 上也能跑出来。

```
QQ 桥接 ──POST /v1/speak/file──► 127.0.0.1:8765（本仓库的兼容层）
                                       │
                                       └──► 127.0.0.1:7880（IndexTTS2 整合包自带的 OpenAI 式 API）
                                                  └──► wav ──► QQ 语音条
```

**不改 SurfCore 一行代码。** 它的语音链路本来就只认一个 HTTP 契约
（`POST /v1/speak/file` → wav），本仓库把这个契约实现掉，后端随便换。

---

## 它解决什么问题

| 原方案 | 本方案 |
| --- | --- |
| 语音包依赖 `GPT-SoVITS` + CUDA，A 卡完全跑不了 | 走 IndexTTS2，N 卡 / A 卡（ZLUDA）/ CPU 都行 |
| 语音包 1.8 GB 下载 + 20~40 分钟装依赖 | 用现成的 IndexTTS2 Windows 整合包（自带 Python 与模型） |
| 设置页「语音」在没装语音包时永远是「未安装」 | 装一个**占位语音包**，让「启动」按钮正常可用 |

## 前置条件

- Windows 10/11
- 已装好 **SurfCore**（有 `config.json` 和 `src\bridge.js` 的那层目录），QQ 桥接能正常收发
- 已解压 **IndexTTS2 Windows 整合包**，目录里有 `env\pythonw.exe` 和 `api\api.py`
  （本仓库**不分发**任何模型/二进制，请自行获取；推荐解压到
  `<SurfCore>\state\voice-packs`，即 `env\` 和 `api\` 与 `voice-local` 同级）
- 一段 **参考音频**：3~10 秒、干净、单人、无背景音乐。IndexTTS 是零样本克隆，没有它出不了声

## 三步安装

```powershell
# 1) 取代码
git clone https://github.com/<you>/surfcore-indextts-voice.git
cd surfcore-indextts-voice

# 2) 安装（路径会自动找，找不到就传参）
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 `
  -SurfcoreDir "C:\Users\你\Documents\surfcore" `
  -RefAudio "D:\voice\我的参考音频.wav"

# 3) 重启 DSH 客户端 → 设置 → SurfCore → 语音 → 启动
```

> **为什么必须重启 DSH**：她能不能发语音，取决于 MCP server 有没有注册 `qq_send_voice`；
> stdio MCP 的工具清单在 DSH 启动时固定，改完配置不重启，她那边依旧「不会说话」。

验证（不发 QQ 消息）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

它会依次检查 7880 引擎、8765 入口，并真合成一句给你听。

## 用法

| 场景 | 怎么做 |
| --- | --- |
| 她主动说 | QQ 里说「用语音回我一句」；她自己决定用 `qq_send_voice(text=…)` |
| 你手动试 | 设置 → SurfCore → 语音 → 启动，然后打开 <http://127.0.0.1:8765/> 的试音台 |
| 调试合成 | `node scripts\voice-e2e.mjs --base-url http://127.0.0.1:8765`（SurfCore 自带） |
| 排查她有没有工具 | `node .\scripts\probe-tools.mjs --repo "<SurfCore>"`（握手列工具名，不改任何东西） |
| 看日志 | `<voice-packs>\logs\index-tts-api.log`、`logs\shim.log`、`index-tts-bridge\bridge.log` |

## 实测性能

Ryzen 5 5600X + RX 6750 GRE 12G（ZLUDA，`gfx1031`）：

| 文本 | 音频长度 | 合成耗时 |
| --- | --- | --- |
| 嗯，我在。 | 1.15s | 约 22s |
| 今天挺热的，你那边呢？ | 2.5s | 约 32s |
| 首次推理（同一进程第一次，含内核编译） | 3.0s | 约 50 分钟（**仅一次**） |

RTF ≈ 12~20：**能出声，但不是「秒回」**。所以默认把 `maxChars` 压到 80、
`timeoutMs` 放宽到 180 秒。想要更快就缩短句子，或换云端语音包。

## 目录结构

```
bridge/                 SurfCore 契约兼容层（/v1/speak/file → 后端）
  server.py             只用标准库；backend = mock / http / indextts
  config.example.json   后端地址、参考音频映射
pack/                   占位语音包（被复制到 <voice-packs>\voice-local）
  config.toml           SurfCore 判定「已安装」的标记 + [voice.characters]
  launcher.py           判端口、设离线环境、无窗口起子进程
  run.bat / gsv.bat / stop.bat / status.bat
scripts/
  install.ps1           一键安装（幂等）
  verify.ps1            链路体检（不发消息）
  probe-tools.mjs       握手 MCP server，看她到底有没有 qq_send_voice
  uninstall.ps1         卸载（保留模型）
docs/                   安装细节、排错、A 卡说明、配置手册
reference/              参考音频放置说明
```

## 安全与边界

- 只监听 `127.0.0.1`（8765 / 7880），不对外网暴露；8765 不需要 token，安全边界是本机账户级。
- 本仓库**不包含**模型、整合包、ZLUDA、IndexTTS 代码，也不修改它们。
- `install.ps1` 只会改 `<SurfCore>\config.json` 里的语音开关，改前自动备份。
- 语音内容仍然走 QQ，平台规则与账号风险由使用者承担。

## 卸载

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1
```

删掉 `voice-local`、`index-tts-bridge`，关掉 `tts.enabled` / `sendVoice`；模型和你的参考音频保留。

## 常见问题（详见 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)）

| 症状 | 先看这里 |
| --- | --- |
| 设置页「启动」超时（60 秒） | 引擎启动时想联网下载 `campplus` 被打断 → [坑 1](docs/TROUBLESHOOTING.md#pit1) |
| 她「不会说话」/ 说没有语音功能 | `socialV2.voice.enabled` 是 false，MCP 没注册工具 → [坑 2](docs/TROUBLESHOOTING.md#pit2) |
| 一合成就是 502 | 系统代理劫持了 127.0.0.1 → [坑 3](docs/TROUBLESHOOTING.md#pit3) |
| 服务活着但客户端 connection reset | `pythonw` 没有 stdout，`print()` 抛异常 → [坑 4](docs/TROUBLESHOOTING.md#pit4) |
| 一堆黑框 cmd 窗口 | 用 cmd + netstat 判端口 → [坑 5](docs/TROUBLESHOOTING.md#pit5) |
| 第一句卡了快一小时 | ZLUDA 首次编译内核（一次性） → [坑 6](docs/TROUBLESHOOTING.md#pit6) |

## 许可

MIT（本仓库的代码）。IndexTTS 模型与整合包遵循各自的许可（bilibili 模型使用协议等），
本仓库不重新分发它们。ZLUDA 为第三方组件。

## 致谢

- [SurfCore](https://github.com/Mieksido/surfcore) —— 语音契约、语音包机制、整套 QQ 链路
- [IndexTTS](https://github.com/index-tts/index-tts) —— bilibili 的零样本 TTS
- 整合包与 ZLUDA 的作者/维护者（见各自发行说明）
