# 安装（手把手）

> 目标：从「SurfCore 能聊天、但语音模块是空的」到「QQ 里收到她的语音条」。
> 全程约 10 分钟（不含下载整合包）。

## 0. 先确认四件事

| 需要 | 怎么确认 |
| --- | --- |
| Windows 10/11 | —— |
| SurfCore 已装好 | 目录里有 `config.json`、`src\bridge.js`；QQ 桥接能收发消息 |
| IndexTTS2 整合包已解压 | 目录里有 `env\pythonw.exe`、`api\api.py`、`checkpoints\config.yaml` |
| 一段参考音频 | 3~10 秒、单人、干净、无 BGM 的 wav/mp3 |

整合包请解压到 **`<SurfCore>\state\voice-packs`**，装完长这样：

```
<SurfCore>\state\voice-packs\
  env\                  ← 整合包自带 Python（含 zluda）
  api\api.py            ← OpenAI 风格的 TTS API（7880）
  checkpoints\          ← 模型
  outputs\  logs\
  voice-local\          ← 本仓库创建的占位语音包
  index-tts-bridge\     ← 本仓库创建的兼容层
```

> 解压到别处也能用：`install.ps1 -VoicePacksDir "D:\IndexTTS2"`，但
> `voice-local` 必须落在 `<SurfCore>\state\voice-packs\voice-local`（SurfCore 只认这个路径）。

## 1. 一键安装

```powershell
cd <本仓库>
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 `
  -SurfcoreDir "<SurfCore 目录>" `
  -VoicePacksDir "<整合包目录>" `
  -RefAudio "<参考音频路径>" `
  -Character xiaoyu
```

`-SurfcoreDir` / `-VoicePacksDir` 可以省略（会自动猜常见位置），`-RefAudio` 强烈建议给。

### 它到底做了什么

| 步骤 | 产物 | 为什么需要 |
| --- | --- | --- |
| 1 | `<voice-packs>\index-tts-bridge\` | 把 SurfCore 的 `/v1/speak/file` 契约翻译成整合包的 `/v1/audio/speech` |
| 2 | `<voice-packs>\voice-local\` | SurfCore 判定「语音包已安装」只看这个目录里的 `config.toml`；「启动」按钮执行它的 `run.bat` |
| 3 | `voice-local\paths.json`、`.venv\Scripts` junction | SurfCore 的 `start()` 会检查 `.venv\Scripts\python.exe`；junction 指向整合包的 `env\` |
| 4 | `api\ckyp\<Character>.wav` | IndexTTS 零样本克隆必须有参考音频 |
| 5 | 修 `checkpoints\hub\models--funasr--campplus\refs\main` | 整合包自带的 HF 缓存指针可能指向空快照，不修会 `LocalEntryNotFound` |
| 6 | 改 `<SurfCore>\config.json` 的语音开关 | `voice.enabled` 是「AI 能不能发语音」的总闸，默认是 false |

改 `config.json` 前会自动备份成 `config.json.bak-<时间戳>`。

## 2. 重启 DSH 客户端

**完全退出再打开**，不是刷新页面。原因：`qq_send_voice` 这个工具由 stdio MCP server 提供，
工具清单在 DSH 启动时拉取一次。不重启 → 她永远看不到这个工具。

## 3. 启动语音服务

设置 → SurfCore → 语音 → **启动**。第一次约 25 秒（加载模型），期间发语音会 502。

等价的手动方式：

```powershell
<voice-packs>\voice-local\run.bat      # 起 7880 + 8765（幂等，已在跑就跳过）
<voice-packs>\voice-local\status.bat   # 看端口
<voice-packs>\voice-local\stop.bat     # 停
```

## 4. 验证

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

输出应当类似：

```
== 1. 引擎 7880
  [ok] 模型已加载
== 2. 入口 8765
  [ok] 入口在线
== 3. 真实合成
  [ok] 合成成功：75,308 字节，用时 36.6 秒
```

也可以直接在浏览器打开 <http://127.0.0.1:8765/> 点「合成并播放」。

## 5. 让她说

QQ 里发一句「用语音回我一句」。

如果她仍然说没有语音能力：

1. 确认 `config.json` 里 `socialV2.voice.enabled` 和 `socialV2.tools.sendVoice` 都是 `true`；
2. 确认重启过 DSH（见第 2 步）；
3. 结束那个 QQ 会话再发一条消息（旧会话可能缓存了旧工具表）。

## 手动安装（不想跑脚本）

```powershell
$packs = "<SurfCore>\state\voice-packs"

# 1) 兼容层
mkdir "$packs\index-tts-bridge"
copy bridge\server.py      "$packs\index-tts-bridge\server.py"
copy bridge\config.example.json "$packs\index-tts-bridge\config.json"

# 2) 占位语音包
mkdir "$packs\voice-local"
copy pack\* "$packs\voice-local\"

# 3) paths.json（把下面四条改成你的真实路径，用 / 分隔）
@'
{
  "pythonw":     "C:/.../state/voice-packs/env/pythonw.exe",
  "api_py":      "C:/.../state/voice-packs/api/api.py",
  "shim_server": "C:/.../state/voice-packs/index-tts-bridge/server.py",
  "shim_config": "C:/.../state/voice-packs/index-tts-bridge/config.json"
}
'@ | Set-Content "$packs\voice-local\paths.json" -Encoding utf8

# 4) .venv junction
cmd /c mklink /J "$packs\voice-local\.venv\Scripts" "$packs\env"

# 5) 参考音频
copy "D:\voice\me.wav" "$packs\api\ckyp\xiaoyu.wav"

# 6) 打开 config.json，把 socialV2.voice.enabled / voice.tts.enabled / tools.sendVoice 设为 true
```

## 升级 / 重装

直接重跑 `install.ps1`。它会覆盖 `bridge\`、`pack\` 里的文件，但**保留**你已有的
`index-tts-bridge\config.json`（参考音频映射在里面）和 `api\ckyp\` 里的音频。
