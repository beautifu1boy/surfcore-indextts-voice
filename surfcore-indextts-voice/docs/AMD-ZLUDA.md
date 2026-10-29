# A 卡（AMD）说明

这套东西最初就是为了解决"A 卡跑不了 SurfCore 原配语音包"。

## 为什么原方案不行

SurfCore 的本地语音包 = `voxd`(8765) + **GPT-SoVITS**(9880)。后者是 CUDA 生态：
`torch + cu118`、自定义 CUDA kernel、fp16。Windows 上的 AMD 显卡没有可用的 CUDA，
装完要么报错，要么退回 CPU 慢到不可用。

## 这套方案怎么绕过去

1. 用 **IndexTTS2 整合包**，它自带一个 `env\`（conda Python 3.10）和 **ZLUDA**；
2. `api.py` 第一行就 `import zluda`，它把 CUDA 调用翻译成 ROCm/HIP 调用；
3. 于是 `torch.cuda.is_available()` 返回 `True`，设备名是
   `AMD Radeon RX 6750 GRE 12GB [ZLUDA]`；
4. 我们只跟它的 HTTP API（7880）说话，完全不碰底层。

实测（RX 6750 GRE 12G / gfx1031 / ROCm 6）：

```
torch 2.2.2+cu118
cuda_available True
device AMD Radeon RX 6750 GRE 12GB [ZLUDA]
```

## 真实速度

| 场景 | RTF | 说明 |
| --- | --- | --- |
| 首次推理（同一进程第一次） | —— | 约 50 分钟，几乎全花在编译内核上 |
| 之后（短句） | 12~20 | 1.15 秒音频 ≈ 22 秒；2.5 秒音频 ≈ 32 秒 |

对比官方在 RTX 4090 上的 RTF 0.32，差了两个数量级。原因不是模型，而是 ZLUDA 的
翻译层 + 部分算子回落到 CPU。**能听，但别期待"秒回"。**

## 想更快的话

| 方向 | 代价 |
| --- | --- |
| 缩短句子（`maxChars` 20~40） | 语音条更短，但等待明显变短 |
| 换 40/50 系 N 卡 | 直接吃 CUDA，RTF 0.3 量级 |
| 用云端语音包（SurfCore 自带 8767） | 按字符计费，不占显卡 |
| WSL2 + 原生 ROCm | 要重装整套依赖，且整合包的 ZLUDA 补丁用不上 |

## 显存与并发

- 模型常驻约 3~4 GB（fp16）。
- **并发必须为 1**：`launcher.py` 用单实例 + 端口探测避免重复加载；`server.py` 用
  `LOCK` 串行化合成请求。两个进程同时加载模型在 12G 卡上会 OOM。
- 推理期间 uvicorn 的事件循环是被阻塞的 —— 这时连 `/health` 都会超时，属于**正常现象**，
  不要据此判断服务挂了。

## 已知限制

- ZLUDA 的兼容性跟着整合包的 `rocm6\` 走，**别自己升级 torch**；
- 整合包更新后 `refs/main` 可能再次指向空快照（见 [坑 1](TROUBLESHOOTING.md#pit1)），
  重跑 `install.ps1` 即可；
- `ffprobe` 不在 PATH 时会提示"无法探测时长"（只警告，不影响发送）。
