<#
.SYNOPSIS
    把 IndexTTS2 接进 SurfCore 的语音模块（替换 voxd + GPT-SoVITS）。

.DESCRIPTION
    做五件事，全部幂等，可以反复跑：
      1. 把 bridge\ 复制到 <voice-packs>\index-tts-bridge（SurfCore 契约兼容层）
      2. 生成占位语音包 <voice-packs>\voice-local（让设置页「启动」按钮可用）
      3. 写 paths.json、建 .venv\Scripts junction（SurfCore 的启动前置检查）
      4. 修 HuggingFace 缓存里 campplus 的 refs 指针（整合包离线启动必需）
      5. 打开 SurfCore config.json 里的语音开关（voice.enabled / tts.enabled / sendVoice）

    不改 SurfCore 的任何代码，不动 index-tts 整合包的任何文件（除了 ckyp 参考音频）。

.PARAMETER SurfcoreDir
    SurfCore 仓库根（有 config.json 和 src\bridge.js 的那层）。不传就自动找
    $env:SURFCORE_DIR → ~\Documents\surfcore → ~\surfcore → D:\surfcore。

.PARAMETER VoicePacksDir
    IndexTTS2 整合包解压到的目录（里面有 env\pythonw.exe 和 api\api.py）。
    默认 <SurfcoreDir>\state\voice-packs。

.PARAMETER RefAudio
    参考音频（3~10 秒、干净、单人）的路径。会被复制成 api\ckyp\<Character>.wav。
    不传就沿用整合包里已有的 <Character>.wav。

.PARAMETER Character
    角色名，默认 xiaoyu。要和 pack\config.toml 的 [voice.characters] 对得上。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1

.EXAMPLE
    .\scripts\install.ps1 -SurfcoreDir D:\surfcore -RefAudio "D:\voice\me.wav" -Character xiaoyu
#>
[CmdletBinding()]
param(
    [string]$SurfcoreDir = '',
    [string]$VoicePacksDir = '',
    [string]$RefAudio = '',
    [string]$Character = 'xiaoyu',
    [switch]$SkipSurfcoreConfig
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "   [ok] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "   [!] $msg" -ForegroundColor Yellow }
function Die($msg) { Write-Host "   [x] $msg" -ForegroundColor Red; exit 1 }

function Resolve-SurfcoreDir {
    param([string]$Given)
    if ($Given) { return (Resolve-Path $Given).Path }
    $candidates = @()
    if ($env:SURFCORE_DIR) { $candidates += $env:SURFCORE_DIR }
    $candidates += (Join-Path $HOME 'Documents\surfcore')
    $candidates += (Join-Path $HOME 'surfcore')
    $candidates += 'D:\surfcore'
    foreach ($c in $candidates) {
        if ($c -and (Test-Path (Join-Path $c 'config.json'))) { return (Resolve-Path $c).Path }
    }
    return ''
}

function Set-JsonValue {
    param($Object, [string[]]$Path, $Value)
    $cur = $Object
    for ($i = 0; $i -lt $Path.Length - 1; $i++) {
        $key = $Path[$i]
        if (-not $cur.PSObject.Properties[$key]) {
            $cur | Add-Member -MemberType NoteProperty -Name $key -Value ([pscustomobject]@{}) -Force
        }
        if ($null -eq $cur.$key -or $cur.$key -isnot [pscustomobject]) {
            $cur.$key = [pscustomobject]@{}
        }
        $cur = $cur.$key
    }
    $last = $Path[-1]
    if ($cur.PSObject.Properties[$last]) { $cur.$last = $Value }
    else { $cur | Add-Member -MemberType NoteProperty -Name $last -Value $Value -Force }
}

# ── 0. 找目录 ────────────────────────────────────────────────────────────────
Step '定位目录'
$SurfcoreDir = Resolve-SurfcoreDir $SurfcoreDir
if (-not $SurfcoreDir) { Die '找不到 SurfCore 目录：用 -SurfcoreDir 指定（有 config.json 的那层）' }
if (-not $VoicePacksDir) { $VoicePacksDir = Join-Path $SurfcoreDir 'state\voice-packs' }
if (-not (Test-Path $VoicePacksDir)) { Die "语音包目录不存在：$VoicePacksDir" }
$VoicePacksDir = (Resolve-Path $VoicePacksDir).Path

$PyW = Join-Path $VoicePacksDir 'env\pythonw.exe'
$ApiPy = Join-Path $VoicePacksDir 'api\api.py'
if (-not (Test-Path $PyW)) { Die "没找到整合包的 python：$PyW`n   先把 IndexTTS2 整合包解压到 $VoicePacksDir（要有 env\ 和 api\）" }
if (-not (Test-Path $ApiPy)) { Die "没找到整合包的 API：$ApiPy" }
Ok "SurfCore   : $SurfcoreDir"
Ok "语音包目录 : $VoicePacksDir"

# ── 1. 复制兼容层 ────────────────────────────────────────────────────────────
Step '安装兼容层（index-tts-bridge）'
$BridgeDir = Join-Path $VoicePacksDir 'index-tts-bridge'
New-Item -ItemType Directory -Force -Path $BridgeDir | Out-Null
Copy-Item (Join-Path $RepoRoot 'bridge\server.py') (Join-Path $BridgeDir 'server.py') -Force
Copy-Item (Join-Path $RepoRoot 'bridge\run.bat') (Join-Path $BridgeDir 'run.bat') -Force
Copy-Item (Join-Path $RepoRoot 'bridge\README.md') (Join-Path $BridgeDir 'README.md') -Force -ErrorAction SilentlyContinue
$BridgeCfg = Join-Path $BridgeDir 'config.json'
if (-not (Test-Path $BridgeCfg)) {
    Copy-Item (Join-Path $RepoRoot 'bridge\config.example.json') $BridgeCfg -Force
    Ok "已生成 config.json（参考音频用 api\ckyp\<角色>.wav）"
} else {
    Ok "已存在 config.json，保留你的改动"
}

# ── 2. 占位语音包 ────────────────────────────────────────────────────────────
Step '安装占位语音包（voice-local）'
$PackDir = Join-Path $VoicePacksDir 'voice-local'
New-Item -ItemType Directory -Force -Path $PackDir | Out-Null
foreach ($f in @('config.toml', 'launcher.py', 'run.bat', 'gsv.bat', 'stop.bat', 'status.bat')) {
    Copy-Item (Join-Path $RepoRoot "pack\$f") (Join-Path $PackDir $f) -Force
}
Ok "已写入 $PackDir"

# ── 3. paths.json + .venv junction ───────────────────────────────────────────
Step '写 paths.json 与 .venv 链接'
$paths = [ordered]@{
    pythonw     = $PyW -replace '\\', '/'
    api_py      = $ApiPy -replace '\\', '/'
    shim_server = (Join-Path $BridgeDir 'server.py') -replace '\\', '/'
    shim_config = $BridgeCfg -replace '\\', '/'
}
$pathsJson = $paths | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $PackDir 'paths.json'), $pathsJson, (New-Object Text.UTF8Encoding($false)))
Ok 'paths.json 已生成'

$VenvScripts = Join-Path $PackDir '.venv\Scripts'
if (-not (Test-Path (Join-Path $VenvScripts 'python.exe'))) {
    New-Item -ItemType Directory -Force -Path (Split-Path $VenvScripts -Parent) | Out-Null
    if (Test-Path $VenvScripts) { Remove-Item $VenvScripts -Recurse -Force -ErrorAction SilentlyContinue }
    # SurfCore 的 start() 会检查 <pack>\.venv\Scripts\python.exe 是否存在；
    # 指向整合包的 env 既满足检查，又保证真执行时用的就是那个解释器。
    $j = cmd /c "mklink /J `"$VenvScripts`" `"$(Join-Path $VoicePacksDir 'env')`" 2>&1"
    if (-not (Test-Path (Join-Path $VenvScripts 'python.exe'))) { Die ".venv\Scripts 链接创建失败：$j" }
    Ok '.venv\Scripts -> env（junction）'
} else {
    Ok '.venv\Scripts 已就绪'
}

# ── 4. 参考音频 ──────────────────────────────────────────────────────────────
Step '参考音频'
$CkypDir = Join-Path $VoicePacksDir 'api\ckyp'
New-Item -ItemType Directory -Force -Path $CkypDir | Out-Null
$refName = "$Character.wav"
$refPath = Join-Path $CkypDir $refName
if ($RefAudio) {
    if (-not (Test-Path $RefAudio)) { Die "参考音频不存在：$RefAudio" }
    Copy-Item $RefAudio $refPath -Force
    Ok "已复制 -> $refPath"
} elseif (Test-Path $refPath) {
    Ok "沿用已有参考音频：$refPath"
} else {
    $any = Get-ChildItem $CkypDir -Filter *.wav -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($any) { Warn "没有 $refName，但目录里已有 $($any.Name)，请确认 bridge\config.json 的 voices 指向它" }
    else { Warn "api\ckyp 里没有参考音频：IndexTTS 是零样本克隆，没有参考音频出不了声。请用 -RefAudio 指定，或手动放一个 $refName" }
}

# ── 5. 修 HuggingFace 缓存里的 campplus ──────────────────────────────────────
Step '检查 campplus 缓存'
$CpRoot = Join-Path $VoicePacksDir 'checkpoints\hub\models--funasr--campplus'
if (Test-Path $CpRoot) {
    $refFile = Join-Path $CpRoot 'refs\main'
    $binName = 'campplus_cn_common.bin'
    $resolvedOk = $false
    if (Test-Path $refFile) {
        $ref = (Get-Content $refFile -Raw).Trim()
        if ($ref -and (Test-Path (Join-Path $CpRoot "snapshots\$ref\$binName"))) { $resolvedOk = $true }
    }
    if (-not $resolvedOk) {
        $snap = Get-ChildItem (Join-Path $CpRoot 'snapshots') -Directory -ErrorAction SilentlyContinue |
                Where-Object { Test-Path (Join-Path $_.FullName $binName) } | Select-Object -First 1
        if ($snap) {
            [IO.File]::WriteAllText($refFile, $snap.Name, (New-Object Text.UTF8Encoding($false)))
            Ok "已把 refs/main 指回 $($snap.Name)（原来的指针指向空快照，离线启动会报 LocalEntryNotFound）"
        } else {
            Warn '缓存里找不到 campplus_cn_common.bin：整合包的 API 启动时可能需要联网下载'
        }
    } else {
        Ok '缓存指针正常'
    }
} else {
    Warn '没有发现 campplus 缓存目录（整合包可能没解压完整）'
}

# ── 6. 打开 SurfCore 的语音开关 ─────────────────────────────────────────────
if (-not $SkipSurfcoreConfig) {
    Step '打开 SurfCore 语音开关'
    $cfgFile = Join-Path $SurfcoreDir 'config.json'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Copy-Item $cfgFile "$cfgFile.bak-$stamp" -Force
    $cfg = Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $cfg.socialV2) { $cfg | Add-Member -NotePropertyName socialV2 -NotePropertyValue ([pscustomobject]@{}) -Force }
    Set-JsonValue $cfg @('socialV2', 'voice', 'enabled') $true
    Set-JsonValue $cfg @('socialV2', 'voice', 'tts', 'enabled') $true
    Set-JsonValue $cfg @('socialV2', 'voice', 'tts', 'character') $Character
    Set-JsonValue $cfg @('socialV2', 'voice', 'tts', 'timeoutMs') 180000
    Set-JsonValue $cfg @('socialV2', 'voice', 'tts', 'maxChars') 80
    Set-JsonValue $cfg @('socialV2', 'voice', 'tts', 'route') 'local'
    Set-JsonValue $cfg @('socialV2', 'voice', 'tts', 'baseUrl') 'http://127.0.0.1:8765'
    Set-JsonValue $cfg @('socialV2', 'voice', 'tts', 'endpoints', 'local') 'http://127.0.0.1:8765'
    Set-JsonValue $cfg @('socialV2', 'voice', 'tts', 'endpoints', 'cloud') 'http://127.0.0.1:8767'
    Set-JsonValue $cfg @('socialV2', 'tools', 'sendVoice') $true
    $out = $cfg | ConvertTo-Json -Depth 40
    [IO.File]::WriteAllText($cfgFile, $out, (New-Object Text.UTF8Encoding($false)))
    Ok "已开启 voice.enabled / tts.enabled / tools.sendVoice（备份：config.json.bak-$stamp）"
}

# ── 完成 ────────────────────────────────────────────────────────────────────
Write-Host ''
Write-Host '安装完成。接下来：' -ForegroundColor Green
Write-Host '  1) 完全退出并重启 DSH（必须：MCP 工具清单在启动时固定，不重启她看不到 qq_send_voice）'
Write-Host '  2) 设置 → SurfCore → 语音 → 启动（约 25 秒模型加载）'
Write-Host "  3) 验证：powershell -ExecutionPolicy Bypass -File `"$PSScriptRoot\verify.ps1`""
Write-Host ''
