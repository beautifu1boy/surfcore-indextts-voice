# bridge —— SurfCore 语音契约兼容层

一个**只用 Python 标准库**的 HTTP 服务，把 SurfCore 要的 `POST /v1/speak/file`
翻译成 IndexTTS2 整合包的 `/v1/audio/speech`。

```
SurfCore 桥接（node）
    │  POST /v1/speak/file  {text, format:"wav", sr, cache, character}
    ▼
bridge/server.py  :8765
    │  POST /v1/audio/speech  {model, input, voice:<参考音频>, response_format:"wav"}
    ▼
整合包 api/api.py :7880  →  IndexTTS2  →  wav
```

## 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/v1/speak/file` | SurfCore 契约。返回 wav + `X-Duration-Ms` + `X-Cached` |
| POST | `/say` | voxd 插件引擎契约（另一种接法，`format` 配 `voxd` 时用） |
| GET | `/v1/health` | `{ok, engines, cache, uptime_s, served}` |
| GET | `/v1/engines` | 引擎列表 |
| GET | `/` | 试音台（浏览器里点一下就能听） |

## backend

| 值 | 行为 |
| --- | --- |
| `http` | 转发给 `http_backend.url`（`format=openai` 或 `voxd`） |
| `indextts` | 进程内 `import indextts.infer_v2`（需要带 torch 的环境跑本文件） |
| `mock` | 吐正弦波，只用来验证链路（不发人声） |

## 单独跑（调试用）

```bat
run.bat
```

或：

```bat
python server.py --config config.json --port 8765
```

## 三个必须知道的实现细节

1. **绕过系统代理**：Python 的 `urllib` 会把发往 `127.0.0.1` 的请求也交给系统代理
   （读注册表），代理回 502。所以所有出站请求都走 `ProxyHandler({})` 的 opener。
2. **日志不能弄死请求**：`pythonw` 下 `sys.stdout` 可能是 `None` 或坏管道，`print()`
   会抛异常；`log()` 把写文件和打印都包了 `try`。
3. **串行合成**：一把全局锁，同一时刻只跑一个 `synth()`。CPU / 单卡经不起并发。

## 返回错误时的语义

| 状态 | 含义 | SurfCore 侧行为 |
| --- | --- | --- |
| 400 | 文本为空 / 非法 JSON | 报错给模型，让它改说话内容 |
| 413 | 超过 `max_chars` | 同上，建议拆句 |
| 503 | 后端没起来 / 合成失败（`detail` 是可读中文） | 模型会改回打字 |
| 200 | wav 字节 | 正常发语音 |
