#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""IndexTTS 语音包的启动器 —— SurfCore「语音 → 启动」按钮实际执行的就是它。

它做三件事：
  1. 探端口（7880 引擎 / 8765 入口），**没起才起**。绝不重复拉模型：
     api.py 会先把模型塞进显存再绑定端口，重复启动在 12G 卡上很容易 OOM。
  2. 给子进程准备环境（UTF-8 + HuggingFace 离线）。整合包启动时会
     hf_hub_download("funasr/campplus")，网络不通就抛 ReadTimeout 把整个 API
     拖死——模型本来就在 checkpoints\\hub 里，强制离线最稳。
  3. 用 DETACHED_PROCESS + CREATE_NO_WINDOW 起子进程：
     SurfCore 是 spawn(cmd, {detached:true}) 调我们的，Windows 上 detached 会
     新开控制台窗口，用户会看到一堆黑框（还以为是下载器）。

用法：
  pythonw launcher.py          # 两个都检查，缺哪个起哪个
  pythonw launcher.py api      # 只保证引擎（7880）
  pythonw launcher.py shim     # 只保证入口（8765）
  pythonw launcher.py status   # 只打印端口状态，不启动任何东西

路径来源：同目录的 paths.json（由 scripts/install.ps1 生成）。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))     # <voice-packs>\voice-local
BASE = os.path.dirname(HERE)                          # <voice-packs>

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

DEFAULTS = {
    "pythonw": os.path.join(BASE, "env", "pythonw.exe"),
    "api_py": os.path.join(BASE, "api", "api.py"),
    "shim_server": "",
    "shim_config": "",
}


def load_paths() -> dict:
    cfg = dict(DEFAULTS)
    path = os.path.join(HERE, "paths.json")
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            cfg.update({k: v for k, v in json.load(fh).items() if v})
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"paths.json 读取失败（{exc}），使用默认值", file=sys.stderr)
    return cfg


def port_open(port: int, timeout: float = 0.5) -> bool:
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def child_env() -> dict:
    env = os.environ.copy()
    env.update({
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "HF_HOME": os.path.join(BASE, "checkpoints") + os.sep,
        "XDG_CACHE_HOME": os.path.join(BASE, "checkpoints") + os.sep,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_ENDPOINT": "https://hf-mirror.com",
    })
    return env


def launch(args: list, log_name: str) -> None:
    logs = os.path.join(BASE, "logs")
    os.makedirs(logs, exist_ok=True)
    path = os.path.join(logs, log_name)
    with open(path, "ab") as log:
        log.write(f"\n--- launcher {os.path.basename(args[0])} @ {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n".encode("utf-8"))
        log.flush()
        subprocess.Popen(
            args,
            cwd=BASE,
            env=child_env(),
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
            close_fds=True,
        )


def main(argv: list) -> int:
    what = (argv[1] if len(argv) > 1 else "all").lower()
    paths = load_paths()

    if what == "status":
        print(f"engine 7880: {'up' if port_open(7880) else 'down'}")
        print(f"shim   8765: {'up' if port_open(8765) else 'down'}")
        return 0

    if what in ("all", "api"):
        if not os.path.isfile(paths["pythonw"]):
            print(f"找不到 pythonw：{paths['pythonw']}（整合包没解压到 state\\voice-packs？）", file=sys.stderr)
            return 2
        if not os.path.isfile(paths["api_py"]):
            print(f"找不到 api.py：{paths['api_py']}", file=sys.stderr)
            return 2
        if not port_open(7880):
            launch([paths["pythonw"], "-u", paths["api_py"], "--host", "127.0.0.1", "--port", "7880"],
                   "index-tts-api.log")

    if what in ("all", "shim"):
        if not paths["shim_server"] or not os.path.isfile(paths["shim_server"]):
            print("paths.json 里的 shim_server 不存在：先跑 scripts\\install.ps1", file=sys.stderr)
            return 2
        if not port_open(8765):
            launch([paths["pythonw"], paths["shim_server"], "--config", paths["shim_config"]], "shim.log")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
