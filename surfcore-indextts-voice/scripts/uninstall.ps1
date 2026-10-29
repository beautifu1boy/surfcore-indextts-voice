<#
.SYNOPSIS
    卸载本仓库装进 SurfCore 的东西（不动 IndexTTS 整合包本体与模型）。

.DESCRIPTION
    删除：<voice-packs>\voice-local、<voice-packs>\index-tts-bridge
    关闭：config.json 里的 tts.enabled / tools.sendVoice
    保留：整合包的 env / api / checkpoints / outputs，以及你的参考音频。
#>
[CmdletBinding()]
param(
    [string]$SurfcoreDir = '',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }

if (-not $SurfcoreDir) {
    foreach ($c in @($env:SURFCORE_DIR, (Join-Path $HOME 'Documents\surfcore'), (Join-Path $HOME 'surfcore'), 'D:\surfcore')) {
        if ($c -and (Test-Path (Join-Path $c 'config.json'))) { $SurfcoreDir = $c; break }
    }
}
if (-not $SurfcoreDir) { Write-Host '找不到 SurfCore 目录，用 -SurfcoreDir 指定' -ForegroundColor Red; exit 1 }
$SurfcoreDir = (Resolve-Path $SurfcoreDir).Path
$Packs = Join-Path $SurfcoreDir 'state\voice-packs'

Step '停止语音服务'
$stop = Join-Path $Packs 'voice-local\stop.bat'
if (Test-Path $stop) { if (-not $DryRun) { cmd /c "`"$stop`"" | Out-Null }; Write-Host '   已尝试停止 8765 / 7880' }
else { Write-Host '   没有 stop.bat，跳过' }

Step '删除安装目录'
foreach ($d in @((Join-Path $Packs 'voice-local'), (Join-Path $Packs 'index-tts-bridge'))) {
    if (Test-Path $d) {
        if ($DryRun) { Write-Host "   [dry-run] 会删除 $d" }
        else { Remove-Item $d -Recurse -Force; Write-Host "   已删除 $d" }
    } else { Write-Host "   不存在：$d" }
}

Step '关闭 SurfCore 里的语音开关'
$cfgFile = Join-Path $SurfcoreDir 'config.json'
$cfg = Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($cfg.socialV2.voice.tts) { $cfg.socialV2.voice.tts.enabled = $false }
if ($cfg.socialV2.tools) { $cfg.socialV2.tools.sendVoice = $false }
if ($DryRun) {
    Write-Host '   [dry-run] 会把 tts.enabled / tools.sendVoice 设为 false'
} else {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Copy-Item $cfgFile "$cfgFile.bak-$stamp" -Force
    [IO.File]::WriteAllText($cfgFile, ($cfg | ConvertTo-Json -Depth 40), (New-Object Text.UTF8Encoding($false)))
    Write-Host "   已关闭（备份 config.json.bak-$stamp）"
}

Write-Host "`n完成。重启 DSH 后语音模块会回到「未安装」。`n" -ForegroundColor Green
