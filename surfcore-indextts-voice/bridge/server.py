#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""index-tts-bridge —— 用 IndexTTS(2.x) 顶替 voxd/GPT-SoVITS，给 SurfCore 供语音。

为什么需要它：
  SurfCore 的 QQ 语音链路只认一个 HTTP 契约（src/voice-tts.js）：
      POST {baseUrl}/v1/speak/file
      {"text": "...", "format": "wav", "sr": 24000, "cache": true,
       "character": "xiaoyu"?, "voice": "..."?, "style": {...}?}
      <- 200 + wav 字节，响应头 X-Duration-Ms / X-Cached

原方案里这个 baseUrl 是 voxd(8765)，voxd 再转给 GPT-SoVITS(9880，CUDA)。
本文件直接把 8765 这个契约实现掉，后端换成 IndexTTS，于是：
  桥接 → 8765 → IndexTTS → wav → QQ 语音条
SurfCore 一行都不用改（它的默认 endpoints.local 就是 http://127.0.0.1:8765）。

后端（config.json 的 backend 字段）：
  mock      —— 不出声的假音频，只用来验证 HTTP 契约/联通性（默认）
  indextts  —— 进程内 import 官方 IndexTTS（要装好 torch + indextts）
  http      —— 转发给任何会说 HTTP 的 IndexTTS 服务/整合包（/say 或自定义路径）

只用标准库；numpy/torch 只在实际用到 indextts 后端时才 import。
"""

from __future__ import annotations

import io
import json
import os
import queue
import sys
import threading
import time
import traceback
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "config.json")


# ─────────────────────────── 工具 ───────────────────────────


def log(msg: str) -> None:
    """写日志。**永远不能让日志把请求弄死**。

    踩过的坑：用 pythonw 起服务时 sys.stdout 可能是 None 或者是个已经关掉的管道
    （父进程退出后句柄失效），此时 print() 会抛 AttributeError/OSError，
    而它正好在请求处理路径上 —— 结果就是客户端看到 "connection reset"，
    但服务端日志里什么都没有。所以这里两层都包住。
    """
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    path = STATE.get("log_file")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
    try:
        print(line, flush=True)
    except Exception:  # noqa: BLE001
        pass


def wav_duration_ms(raw: bytes) -> int:
    """按 wav 头算时长。不是 wav（裸 PCM）就返回 0，不抛。"""
    try:
        if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
            return 0
        with wave.open(io.BytesIO(raw)) as w:
            rate = w.getframerate() or 0
            if not rate:
                return 0
            return int(round(w.getnframes() * 1000.0 / rate))
    except Exception:
        return 0


def load_config(path: str) -> dict:
    cfg = {
        "host": "127.0.0.1",
        "port": 8765,
        "backend": "mock",
        "max_chars": 400,
        "log_file": os.path.join(HERE, "bridge.log"),
        "voices": {"default": {"ref_audio": "", "ref_text": ""}},
        "indextts": {
            "repo": "",
            "cfg_path": "",
            "model_dir": "",
            "use_fp16": False,
            "use_cuda_kernel": False,
            "use_deepspeed": False,
            "device": "",
        },
        "http_backend": {
            "url": "http://127.0.0.1:7860",
            "path": "/say",
            "timeout": 180,
            "headers": {},
        },
    }
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8-sig") as fh:
            user = json.load(fh)
        for key, value in user.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    return cfg


# ─────────────────────────── 后端 ───────────────────────────


class BackendError(Exception):
    """合成失败：message 会原样回给 SurfCore，所以要写成人能看懂的话。"""


class MockBackend:
    name = "mock"

    def __init__(self, cfg: dict):
        self.sr = 24000

    def load(self) -> None:
        log("backend=mock：只吐 0.6 秒 440Hz 正弦，用来验证 HTTP 契约")

    def synth(self, text: str, voice: dict, lang: str = "zh") -> bytes:
        # 时长跟字数走一点，方便肉眼确认"不同的句子拿到不同的音频"
        seconds = 0.3 + min(len(text), 40) * 0.02
        n = int(self.sr * seconds)
        frames = bytearray()
        import math

        for i in range(n):
            v = int(8000 * math.sin(2 * math.pi * 440 * i / self.sr))
            frames += int(v).to_bytes(2, "little", signed=True)
        return pcm_to_wav(bytes(frames), self.sr)


def _no_proxy_opener():
    """不走系统代理的 opener。

    踩过的坑：Windows 上开着 Clash/系统代理时，Python 的 urllib 会把
    **发往 127.0.0.1 的请求也丢给代理**（getproxies() 读注册表），
    代理对 localhost 返回 502 —— 现象是"本地服务明明活着，却一直 502"。
    node 的 fetch 不吃系统代理，所以只在 Python 侧复现。
    """
    import urllib.request

    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


class FailingBackend:
    """后端没起来时的占位：**宁可 503，也不要吐正弦波**。

    否则 SurfCore 会把提示音当成人声发进群里，排查时还以为是模型跑出来的。
    """

    name = "unavailable"

    def __init__(self, error: str):
        self.error = error

    def load(self) -> None:
        pass

    def synth(self, text: str, voice: dict, lang: str = "zh") -> bytes:
        raise BackendError(f"语音后端没起来：{self.error}")


class HttpBackend:
    """把请求转给任何会说 HTTP 的外部 TTS（整合包/自建服务）。

    两种外部契约，用 http_backend.format 选：

    `openai`（IndexTTS2 整合包 / OpenAI 兼容服务）：
        POST {url}{path}   path 默认 /v1/audio/speech
        {"model":"index-tts2","input":"...","voice":"<参考音频文件名或绝对路径>","response_format":"wav"}
        <- 200 + wav 字节

    `voxd`（voxd 的插件引擎契约，通用）：
        POST {url}{path}   path 默认 /say
        {"text":"...","lang":"zh","voice":{"id","ref_audio","ref_text"},"instruct":null}
        <- 200 + wav 字节
    """

    name = "http"

    def __init__(self, cfg: dict):
        hb = cfg.get("http_backend") or {}
        self.fmt = str(hb.get("format") or "voxd").lower()
        self.url = str(hb.get("url") or "").rstrip("/")
        default_path = "/v1/audio/speech" if self.fmt == "openai" else "/say"
        self.path = str(hb.get("path") or default_path)
        if not self.path.startswith("/"):
            self.path = "/" + self.path
        self.timeout = float(hb.get("timeout") or 180)
        self.headers = dict(hb.get("headers") or {})
        self.model = str(hb.get("model") or "index-tts2")
        self.extra = dict(hb.get("extra") or {})
        if not self.url:
            raise BackendError("http 后端没配 http_backend.url")

    def load(self) -> None:
        import urllib.request

        try:
            with _no_proxy_opener().open(f"{self.url}/health", timeout=5) as r:
                r.read(1)
            log(f"backend=http({self.fmt})：{self.url} 在线")
        except Exception as e:  # noqa: BLE001
            log(f"backend=http({self.fmt})：{self.url}/health 探活失败（{e}），仍会尝试合成")

    def _payload(self, text: str, voice: dict, lang: str) -> bytes:
        if self.fmt == "openai":
            # OpenAI 的 voice 字段要的是"参考音频"，绝对路径也被整合包接受
            speaker = str(voice.get("ref_audio") or voice.get("id") or "")
            body = {
                "model": self.model,
                "input": text,
                "voice": speaker,
                "response_format": "wav",
                "speed": float(voice.get("speed") or 1.0),
            }
        else:
            body = {
                "text": text,
                "lang": lang or "zh",
                "voice": {
                    "id": voice.get("id", ""),
                    "ref_audio": voice.get("ref_audio"),
                    "ref_text": voice.get("ref_text"),
                    "preset": voice.get("preset"),
                    "design": voice.get("design"),
                    "speed": voice.get("speed", 1.0),
                },
                "instruct": None,
                "rate": 1.0,
                "pitch": 0.0,
            }
        body.update(self.extra)
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def synth(self, text: str, voice: dict, lang: str = "zh") -> bytes:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            self.url + self.path,
            data=self._payload(text, voice, lang),
            headers={"content-type": "application/json", **self.headers},
        )
        try:
            with _no_proxy_opener().open(req, timeout=self.timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read()[:300].decode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                pass
            raise BackendError(f"外部服务返回 {e.code}：{detail}") from e
        except Exception as e:  # noqa: BLE001
            raise BackendError(f"连不上外部服务 {self.url}：{e}") from e


class IndexTTSBackend:
    """官方 index-tts 仓库，进程内调用。

    需要：
      · 一个有 torch + indextts 的 Python 环境（本文件就要用那个环境跑）
      · config.indextts.repo       指向 clone 下来的 index-tts 仓库根
      · config.indextts.model_dir  指向模型目录（里面有 config.yaml）
      · config.voices.<角色>.ref_audio  参考音频（IndexTTS 是零样本克隆，必须有）
    """

    name = "indextts"

    def __init__(self, cfg: dict):
        it = cfg.get("indextts") or {}
        self.repo = str(it.get("repo") or "")
        self.cfg_path = str(it.get("cfg_path") or "")
        self.model_dir = str(it.get("model_dir") or "")
        self.use_fp16 = bool(it.get("use_fp16"))
        self.use_cuda_kernel = bool(it.get("use_cuda_kernel"))
        self.use_deepspeed = bool(it.get("use_deepspeed"))
        self.device = str(it.get("device") or "").strip()
        self.tts = None
        self._tmpdir = os.path.join(HERE, "tmp")
        os.makedirs(self._tmpdir, exist_ok=True)

    def load(self) -> None:
        if not self.repo or not os.path.isdir(self.repo):
            raise BackendError(f"indextts.repo 不存在：{self.repo!r}")
        if not self.model_dir or not os.path.isdir(self.model_dir):
            raise BackendError(f"indextts.model_dir 不存在：{self.model_dir!r}")
        if not self.cfg_path:
            self.cfg_path = os.path.join(self.model_dir, "config.yaml")
        if not os.path.isfile(self.cfg_path):
            raise BackendError(f"找不到模型配置：{self.cfg_path}")

        if self.repo not in sys.path:
            sys.path.insert(0, self.repo)

        import torch  # noqa: F401  延迟到这里，mock 后端就不需要 torch

        if self.device:
            os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
            device = self.device
        else:
            device = "cuda:0" if torch.cuda.is_available() else "cpu"

        log(f"backend=indextts：torch {torch.__version__}，device={device}")
        from indextts.infer_v2 import IndexTTS2

        kwargs = dict(
            cfg_path=self.cfg_path,
            model_dir=self.model_dir,
            use_fp16=self.use_fp16,
            use_cuda_kernel=self.use_cuda_kernel,
            use_deepspeed=self.use_deepspeed,
        )
        # 不同版本对 device 参数的支持不一致，能传就传
        try:
            self.tts = IndexTTS2(device=device, **kwargs)
        except TypeError:
            self.tts = IndexTTS2(**kwargs)
        log("backend=indextts：模型已加载")

    def synth(self, text: str, voice: dict, lang: str = "zh") -> bytes:
        ref = str(voice.get("ref_audio") or "")
        if not ref or not os.path.isfile(ref):
            raise BackendError(
                "没有可用的参考音频（IndexTTS 是零样本克隆）：请在 config.json 的 "
                f"voices 里给角色配 ref_audio，当前值 {ref!r}"
            )
        out = os.path.join(self._tmpdir, f"gen-{os.getpid()}-{threading.get_ident()}.wav")
        try:
            self.tts.infer(
                spk_audio_prompt=ref,
                text=text,
                output_path=out,
                verbose=False,
            )
            with open(out, "rb") as fh:
                return fh.read()
        except Exception as e:  # noqa: BLE001
            raise BackendError(f"IndexTTS 合成失败：{e}") from e
        finally:
            try:
                os.remove(out)
            except OSError:
                pass


def pcm_to_wav(pcm: bytes, sr: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


# ─────────────────────────── 服务 ───────────────────────────

STATE = {"backend": None, "started": time.time(), "busy": 0, "served": 0}
LOCK = threading.Lock()


def make_backend(cfg: dict):
    kind = str(cfg.get("backend") or "mock").lower()
    if kind == "mock":
        return MockBackend(cfg)
    if kind == "http":
        return HttpBackend(cfg)
    if kind in ("indextts", "index-tts", "index_tts"):
        return IndexTTSBackend(cfg)
    raise BackendError(f"未知 backend：{kind!r}（可选 mock / indextts / http）")


def resolve_voice(cfg: dict, character: str, voice_id: str) -> dict:
    """character 优先（SurfCore 的 tts.character），其次 voice id，最后 default。"""
    voices = cfg.get("voices") or {}
    for key in (character, voice_id, "default"):
        if key and isinstance(voices.get(key), dict):
            entry = dict(voices[key])
            entry["id"] = key
            return entry
    return {"id": character or voice_id or "default", "ref_audio": "", "ref_text": ""}


class Handler(BaseHTTPRequestHandler):
    server_version = "index-tts-bridge/1.0"
    protocol_version = "HTTP/1.1"

    cfg: dict = {}
    backend = None

    # 静默默认的访问日志（改成 print 方便排查）
    def log_message(self, fmt, *args):  # noqa: D102
        if os.environ.get("BRIDGE_VERBOSE"):
            log("http " + fmt % args)

    # ── 工具 ──
    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("content-length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"请求体不是合法 JSON：{e}") from e

    # ── GET ──
    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path in ("/v1/health", "/health", "/v1/healthz"):
            b = self.backend
            return self._json(
                200,
                {
                    "ok": True,
                    "engines": [{"name": getattr(b, "name", "?"), "loaded": True}],
                    "cache": {"entries": 0},
                    "uptime_s": int(time.time() - STATE["started"]),
                    "served": STATE["served"],
                    "busy": STATE["busy"],
                },
            )
        if path == "/v1/engines":
            b = self.backend
            return self._json(200, {"engines": [{"name": getattr(b, "name", "?"), "loaded": True}]})
        if path == "/":
            return self._index()
        return self._json(404, {"ok": False, "error": "not found"})

    # ── POST ──
    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        if path not in ("/v1/speak/file", "/say"):
            return self._json(404, {"ok": False, "error": "not found"})
        try:
            body = self._body()
        except ValueError as e:
            return self._json(400, {"detail": str(e)})

        text = str(body.get("text") or "").strip()
        if not text:
            return self._json(400, {"detail": "要合成的内容是空的"})
        max_chars = int(self.cfg.get("max_chars") or 400)
        if len(text) > max_chars:
            return self._json(413, {"detail": f"文本太长（{len(text)} > {max_chars}）"})

        voice = resolve_voice(self.cfg, str(body.get("character") or ""), str(body.get("voice") or ""))
        lang = str(body.get("lang") or "zh")
        t0 = time.time()
        try:
            # 同一时刻只跑一个合成：CPU/单卡都经不起并发
            with LOCK:
                STATE["busy"] += 1
                try:
                    raw = self.backend.synth(text, voice, lang)
                finally:
                    STATE["busy"] -= 1
        except BackendError as e:
            log(f"合成失败：{e}")
            return self._json(503, {"detail": str(e)})
        except Exception as e:  # noqa: BLE001
            log("合成异常：\n" + traceback.format_exc())
            return self._json(500, {"detail": f"内部错误：{e}"})

        if not raw or len(raw) <= 44:
            return self._json(503, {"detail": "TTS 返回了空音频"})

        ms = int((time.time() - t0) * 1000)
        STATE["served"] += 1
        dur = wav_duration_ms(raw)
        log(f"合成 {len(text)} 字 / {len(raw)} 字节 / 用时 {ms}ms / 音频 {dur}ms / voice={voice.get('id')}")
        self.send_response(200)
        self.send_header("content-type", "audio/wav")
        self.send_header("content-length", str(len(raw)))
        self.send_header("X-Duration-Ms", str(dur))
        self.send_header("X-Cached", "0")
        self.send_header("cache-control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except OSError:
            # 客户端提前断了（超时/取消）：不用管，别把异常打到日志里吓人
            pass

    def _index(self) -> None:
        html = """<!doctype html><meta charset="utf-8"><title>index-tts-bridge 试音台</title>
<body style="font:15px/1.6 system-ui;max-width:720px;margin:40px auto;padding:0 16px">
<h1>index-tts-bridge</h1>
<p>给 SurfCore 用的 <code>/v1/speak/file</code> 兼容层（后端：<b id="b">?</b>）。</p>
<p><input id="t" value="来了来了，我还以为你今天不来了呢" style="width:100%;padding:8px"></p>
<p><button onclick="go()">合成并播放</button> <span id="s"></span></p>
<script>
const b=document.getElementById('b'),s=document.getElementById('s');
fetch('/v1/engines').then(r=>r.json()).then(j=>b.textContent=j.engines[0].name);
async function go(){s.textContent='合成中…';const t=Date.now();
 const r=await fetch('/v1/speak/file',{method:'POST',headers:{'content-type':'application/json'},
   body:JSON.stringify({text:document.getElementById('t').value,format:'wav'})});
 if(!r.ok){s.textContent='失败：'+await r.text();return}
 const blob=await r.blob();s.textContent=`${Date.now()-t}ms，${r.headers.get('x-duration-ms')}ms 音频`;
 new Audio(URL.createObjectURL(blob)).play();}
</script></body>"""
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser("index-tts-bridge")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--backend", default="")
    args = ap.parse_args(argv[1:])

    cfg = load_config(args.config)
    if args.port:
        cfg["port"] = args.port
    if args.backend:
        cfg["backend"] = args.backend
    STATE["log_file"] = cfg.get("log_file")
    log(f"启动：config={args.config} backend={cfg.get('backend')} port={cfg.get('port')}")

    try:
        backend = make_backend(cfg)
        backend.load()
    except BackendError as e:
        log(f"后端启动失败：{e}")
        # 仍然起服务：让 SurfCore 拿到一句能看懂的 503，而不是"服务没起来"
        backend = FailingBackend(str(e))

    Handler.cfg = cfg
    Handler.backend = backend

    host = str(cfg.get("host") or "127.0.0.1")
    port = int(cfg.get("port") or 8765)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    log(f"监听 http://{host}:{port}  （试音台打开浏览器访问根路径）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("收到 Ctrl+C，退出")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
