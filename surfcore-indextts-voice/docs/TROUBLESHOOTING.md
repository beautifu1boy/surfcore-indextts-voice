# 排错

这篇只写**真机上踩过的坑**，每条都带定位方法和根因，不是"重启试试"。

---

<a id="pit1"></a>
## 1. 启动超时 / API 子进程秒退

**现象**

```
启动失败：启动超时（60 秒内端口没起来）
```

同时弹出一个黑框，里面是 `...\env\python.exe`；`logs\index-tts-api.log` 结尾是：

```
requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='cas-bridge.xethub.hf.co', port=443) ...
ERROR:    Application startup failed. Exiting.
```

或者（开了离线之后）：

```
huggingface_hub.errors.LocalEntryNotFoundError: ... cannot find the requested files in the local cache
```

**根因**

整合包的 `api.py` 在 `startup` 里会 `hf_hub_download("funasr/campplus", filename="campplus_cn_common.bin")`：

- 网络能到 HF，但 **Xet 存储（`cas-bridge.xethub.hf.co`）连不上** → 10 秒读超时 → 整个应用退出；
- 强制离线后，HF 按 `checkpoints\hub\models--funasr--campplus\refs\main` 找快照 —— 整合包自带的
  这个指针可能指向一个**空快照**，而真正有文件的快照是另一个（缓存里还会留一个 0 字节的
  `.incomplete` blob）。

**修法**

`install.ps1` 第 5 步会自动修：把 `refs/main` 指向"确实存在 `campplus_cn_common.bin`"的那个快照。
启动器还会给子进程加 `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`，避免它再联网。

手动核对：

```powershell
$cp = "<voice-packs>\checkpoints\hub\models--funasr--campplus"
Get-Content "$cp\refs\main"                                       # 这个 sha
Get-ChildItem "$cp\snapshots" -Recurse -Filter campplus_cn_common.bin   # 文件在哪
```

两者不一致就重跑 `install.ps1`。

---

<a id="pit2"></a>
## 2. 她说自己没有发语音的能力

**现象**：语音模块显示「已启动」，8765/7880 都在，你还是能手动发；但她在 QQ 里说
"我没有语音功能 / 我发不了语音"，并且只回文字。

**根因**：SurfCore 有**两个**开关，名字很像：

| key | 作用 |
| --- | --- |
| `socialV2.voice.tts.enabled` | 现场合成（文字→wav）能不能用 |
| **`socialV2.voice.enabled`** | **AI 能不能发语音（总闸）** |

MCP server 注册 `qq_send_voice` 的条件是**两个都为真**：

```js
if (cfg.socialV2?.voice?.enabled !== false && cfg.socialV2?.tools?.sendVoice !== false) { … }
```

配置模板里 `voice.enabled` 默认是 `false`，所以只开 `tts.enabled` 她依然没有这个工具。
**而且操作者通道（控制台/CLI）不受这个总闸限制** —— 这就是"你能发、她不能发"的原因。

**定位**（不改任何东西，直接问 MCP server 要工具清单）：

```powershell
node .\scripts\probe-tools.mjs --repo "<SurfCore 目录>"
```

它会先把你磁盘上的三个开关打出来，再跟 MCP server 握手列出真实工具表：

```
配置:
  socialV2.voice.enabled        = false
  socialV2.voice.tts.enabled    = true
  socialV2.tools.sendVoice      = true
=> 语音工具不会被注册。把上面两个 false 改成 true，然后重启 DSH。

MCP 注册工具总数: 36
语音相关: (无)
```

**修法**

1. `config.json` 里 `socialV2.voice.enabled = true`（`install.ps1` 会做）；
2. **重启 DSH 客户端** —— stdio MCP 的工具清单是启动时固定的，不重启不会变；
3. 还不行就结束那个 QQ 会话再发消息（旧会话可能缓存了旧工具表）。

---

<a id="pit3"></a>
## 3. 本地服务活着，但一直 502

**现象**：浏览器能打开 <http://127.0.0.1:7880/health>，node 的 `fetch` 也正常；
但桥接/兼容层打过去就是 `HTTP Error 502: Bad Gateway`。

**根因**：机器上开着系统代理（Clash/V2Ray 之类），**Python 的 `urllib` 会把发往 `127.0.0.1`
的请求也交给代理**（`urllib.request.getproxies()` 会读 Windows 注册表里的代理设置）。
代理对 localhost 返回 502。node 的 `fetch` 不吃系统代理，所以只在 Python 侧复现，
现象看起来像"服务坏了"。

**定位**

```powershell
& "<voice-packs>\env\python.exe" -c "import urllib.request;print(urllib.request.getproxies())"
```

**修法**：兼容层已经用 `ProxyHandler({})` 显式绕过代理（`bridge/server.py` 的 `_no_proxy_opener`）。
如果你自己写客户端，记得也绕；`curl.exe` 加 `--noproxy "*"`。

---

<a id="pit4"></a>
## 4. 服务活着，但请求被 reset

**现象**：`/v1/health` 正常，一发合成客户端就 `fetch failed` / `connection reset`，
而服务端日志里什么都没有。

**根因**：用 `pythonw.exe` 起服务时 `sys.stdout` 可能是 `None`，或者是一个"父进程已经退出"的
坏管道。此时 `print()` 抛 `AttributeError/OSError` —— 而它正好在请求处理路径上，
于是连接被直接掐断。

**修法**：`server.py` 的 `log()` 把"写文件"和"print"两段都包了 `try/except`；
`wfile.write` 也吞掉了 `OSError`。如果你自己改代码，别在这两处裸奔。

---

<a id="pit5"></a>
## 5. 点「启动」弹出一堆黑框

**现象**：点启动后冒出 2 个 cmd 窗口，一个在跑 `python.exe`，一个只有
`findstr /c:":7880 "`，看起来像在下载什么东西。

**根因**：

- SurfCore 用 `spawn(cmd, { detached: true })` 调启动脚本，**Windows 上 detached 会给子进程
  新开一个控制台**，`windowsHide` 也压不住；
- 早期版本用 `netstat | findstr` 判端口，那一行命令本身就显示在窗口里。

**修法**：现在的 `run.bat` 只是一行 `start /b pythonw launcher.py`，真正的判断、环境变量、
`DETACHED_PROCESS | CREATE_NO_WINDOW` 都在 `launcher.py` 里做，不再有可见窗口。

另外，`launcher.py` 会**先探端口再启动**：`api.py` 如果被重复拉起，会先把模型塞进显存
再绑端口，12G 卡上很容易 OOM。

---

<a id="pit6"></a>
## 6. 第一次合成就卡 50 分钟

**现象**：日志不停重复 `AMD第一次运行需要编译，请骚等大概10~30分钟`，
一句 3 秒的话跑了 3008 秒。

**根因**：ZLUDA 把 CUDA 内核翻译到 AMD 需要编译，**首次推理**要把用到的内核都编一遍。
实测 1 小时左右（Ryzen 5 5600X）。之后同一进程内就恢复到 20~30 秒/句。

**注意**：目前没找到落盘的编译缓存，所以**每次重启 API 都会再付一次**（实测第二次之后
没那么夸张，约 40 秒；但如果换模型/换驱动可能又变长）。所以：

- 别随手点「停止」；
- 想让语音常驻，把 `voice-local\run.bat` 的快捷方式放进
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`（launcher 幂等，重复执行不会起第二份）。

---

## 还不行？

按顺序收集这三样：

1. `<voice-packs>\logs\index-tts-api.log` 最后 50 行
2. `<voice-packs>\logs\shim.log` 最后 50 行
3. `index-tts-bridge\bridge.log` 最后 20 行

（都**不要**贴 `config.json`、控制台令牌、QQ 号。）
