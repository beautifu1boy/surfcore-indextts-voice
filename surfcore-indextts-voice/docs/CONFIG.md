# 配置手册

三层配置，改哪层取决于你要动什么。

```
① <SurfCore>\config.json                      ← QQ 桥接 + 语音总闸（SurfCore 管）
② <voice-packs>\index-tts-bridge\config.json   ← 兼容层：后端地址、参考音频映射（本仓库）
③ <voice-packs>\env + api\api.py               ← 整合包自己的配置（第三方，不动）
```

## ① SurfCore 的 config.json

安装脚本会写这几个键（其余保持你的原值）：

| 键 | 值 | 含义 |
| --- | --- | --- |
| `socialV2.voice.enabled` | `true` | **AI 能不能发语音的总闸**。false 时 `qq_send_voice` 根本不会注册 |
| `socialV2.voice.tts.enabled` | `true` | 现场合成（文字→wav） |
| `socialV2.voice.tts.character` | `xiaoyu` | 角色名，要和 `pack\config.toml` 的 `[voice.characters]` 对上 |
| `socialV2.voice.tts.timeoutMs` | `180000` | 合成超时。CPU/A 卡慢，别用默认 60 秒 |
| `socialV2.voice.tts.maxChars` | `80` | 单条语音最多多少字。越小越快 |
| `socialV2.voice.tts.route` | `local` | 走 8765（本仓库）；`cloud` 是 8767 |
| `socialV2.voice.tts.endpoints.local` | `http://127.0.0.1:8765` | 本地入口 |
| `socialV2.tools.sendVoice` | `true` | 暴露 `qq_send_voice` / `qq_list_voices` 两个工具 |

> 改完必须**重启桥接**（设置 → QQ → 停止/启动）。桥接在启动时把 config 读进内存。

## ② 兼容层的 config.json

```jsonc
{
  "host": "127.0.0.1",
  "port": 8765,              // SurfCore 默认端点，别改
  "backend": "http",         // http | indextts | mock
  "max_chars": 300,          // 单次请求上限（SurfCore 侧另有 80 字限制）
  "log_file": "bridge.log",

  "http_backend": {          // backend=http 时用
    "url": "http://127.0.0.1:7880",
    "path": "/v1/audio/speech",
    "format": "openai",      // openai = 整合包的 OpenAI 式接口；voxd = 通用 /say
    "model": "index-tts2",
    "timeout": 600,          // 秒；慢机器可以再大
    "headers": {},
    "extra": {}              // 额外塞进 body 的字段
  },

  "indextts": {              // backend=indextts 时用（官方仓库直调，不走整合包）
    "repo": "C:/path/to/index-tts",
    "model_dir": "C:/path/to/index-tts/checkpoints_2",
    "cfg_path": "",          // 空 = model_dir/config.yaml
    "use_fp16": false, "use_cuda_kernel": false, "use_deepspeed": false,
    "device": ""             // 空 = 有 CUDA 用 cuda:0，否则 cpu
  },

  "voices": {                // character → 参考音频
    "default": { "ref_audio": "xiaoyu.wav", "ref_text": "" },
    "xiaoyu":  { "ref_audio": "xiaoyu.wav", "ref_text": "" }
  }
}
```

`ref_audio` 可以直接写**文件名**（相对 `api\ckyp\`），也可以写绝对路径。
SurfCore 传来的 `character` 先查 `voices[character]`，查不到用 `voices.default`。

### backend 怎么选

| 值 | 用途 |
| --- | --- |
| `http` | 默认。对接整合包 / 任何 OpenAI 式 TTS |
| `indextts` | 官方仓库直调，进程内 `import indextts`。需要自带 torch 环境 |
| `mock` | 只吐正弦波，用来验证"SurfCore → 8765"这段是通的（不发人声） |

### 端点

| 路径 | 作用 |
| --- | --- |
| `POST /v1/speak/file` | SurfCore 用的契约：`{text, format, sr, cache, character?, voice?, style?}` → wav |
| `GET /v1/health` | `{ok, engines:[{name,loaded}], cache:{entries}}` |
| `GET /v1/engines` | 引擎列表 |
| `GET /` | 试音台（浏览器点着听） |
| `POST /say` | voxd 插件引擎契约（`format=http` 之外的另一种接法） |

响应头：`X-Duration-Ms`（wav 时长）、`X-Cached`（本服务恒为 0，缓存由 SurfCore 侧做）。

## ③ 整合包这边

- `api.py` 支持 `--host` / `--port` / `--model_dir`，我们的 `launcher.py` 传
  `--host 127.0.0.1 --port 7880`（默认是 `0.0.0.0`，会暴露到局域网，别用默认）。
- 参考音频目录：`api\ckyp\`，也可以 `POST /api/v1/upload` 上传。
- 它的 `/v1/audio/speech` 支持 `voice`（参考音频名/绝对路径）、`speed`。
- **不要**改 `env\` 里的依赖版本，ZLUDA 与 torch 是配套的。
