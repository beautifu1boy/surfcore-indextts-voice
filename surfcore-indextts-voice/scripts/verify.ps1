<#
.SYNOPSIS
    检查 IndexTTS 语音链路是否真的通了（不发 QQ 消息）。

.DESCRIPTION
    依次检查：
      1. 7880 引擎在线且模型已加载
      2. 8765 入口在线
      3. 走一次真实合成（约 20~40 秒），拿回 wav 并打印大小/耗时
    用 curl.exe 并 --noproxy "*"，避免系统代理把 127.0.0.1 的请求也劫走
    （这就是本仓库踩过的 502 坑）。
#>
[CmdletBinding()]
param(
    [string]$Text = '验证一下，能听见我说话吗？',
    [string]$VoicePacksDir = ''
)

$ErrorActionPreference = 'Stop'
function Ok($m) { Write-Host "  [ok] $m" -ForegroundColor Green }
function Bad($m) { Write-Host "  [x]  $m" -ForegroundColor Red }
function Info($m) { Write-Host "       $m" -ForegroundColor DarkGray }

if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    Write-Host '需要 curl.exe（Windows 10/11 自带）。也可以用浏览器打开 http://127.0.0.1:8765/ 点「合成并播放」。' -ForegroundColor Yellow
    exit 1
}

$tmp = Join-Path $env:TEMP ('tts-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

Write-Host "`n== 1. 引擎 7880" -ForegroundColor Cyan
$code = & curl.exe --noproxy '*' -s -o "$tmp\api.json" -w '%{http_code}' --max-time 10 http://127.0.0.1:7880/health
if ($code -ne '200') {
    Bad "7880 无响应（HTTP $code）：语音引擎没起来"
    Info '去 设置 → SurfCore → 语音 → 启动；或双击 <voice-packs>\voice-local\run.bat'
    exit 1
}
$health = Get-Content "$tmp\api.json" -Raw -Encoding UTF8 | ConvertFrom-Json
if ($health.model_loaded -eq $true) { Ok '模型已加载' } else { Bad '模型还没加载完，等一会儿再试'; exit 1 }

Write-Host "`n== 2. 入口 8765" -ForegroundColor Cyan
$code = & curl.exe --noproxy '*' -s -o "$tmp\shim.json" -w '%{http_code}' --max-time 10 http://127.0.0.1:8765/v1/health
if ($code -ne '200') {
    Bad "8765 无响应（HTTP $code）：兼容层没起来"
    Info '同上：点「启动」或跑 run.bat'
    exit 1
}
Ok '入口在线'

Write-Host "`n== 3. 真实合成（第一次可能要等编译，耐心点）" -ForegroundColor Cyan
$body = @{ text = $Text; format = 'wav'; character = 'xiaoyu' } | ConvertTo-Json -Compress
[IO.File]::WriteAllText("$tmp\body.json", $body, (New-Object Text.UTF8Encoding($false)))
$sw = [Diagnostics.Stopwatch]::StartNew()
$out = & curl.exe --noproxy '*' -s -X POST -H 'content-type: application/json' `
    --data-binary "@$tmp\body.json" --max-time 600 `
    -o "$tmp\out.wav" -w '%{http_code}' http://127.0.0.1:8765/v1/speak/file
$sw.Stop()
$size = if (Test-Path "$tmp\out.wav") { (Get-Item "$tmp\out.wav").Length } else { 0 }

if ($out -ne '200' -or $size -lt 1000) {
    Bad "合成失败（HTTP $out，$size 字节）"
    if (Test-Path "$tmp\out.wav") { Info ((Get-Content "$tmp\out.wav" -Raw) -replace "`n", ' ').Substring(0, [Math]::Min(300, $size)) }
    Info '看 <voice-packs>\logs\index-tts-api.log 与 shim.log'
    exit 1
}

Ok ("合成成功：{0:N0} 字节，用时 {1:N1} 秒" -f $size, $sw.Elapsed.TotalSeconds)
Info "音频：$tmp\out.wav"
Start-Process "$tmp\out.wav"
Write-Host "`n链路正常。QQ 里让她「用语音回我一句」即可。`n" -ForegroundColor Green
