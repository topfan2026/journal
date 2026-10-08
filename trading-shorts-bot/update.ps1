# Download the latest bot from GitHub and copy it over this folder.
# Your settings (.env), scanner steps and installed packages are kept.
#   powershell -ExecutionPolicy Bypass -File update.ps1
$ErrorActionPreference = "Stop"
$branch = "claude/inspiring-lamport-eg0e2u"
$url = "https://github.com/topfan2026/journal/archive/refs/heads/$branch.zip"
$zip = Join-Path $env:TEMP "livebot-update.zip"
$tmp = Join-Path $env:TEMP "livebot-update"
$dest = $PSScriptRoot
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Write-Output "downloading $url"
Invoke-WebRequest $url -OutFile $zip -UseBasicParsing
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive $zip -DestinationPath $tmp -Force
$src = Get-ChildItem $tmp -Directory | Select-Object -First 1
Copy-Item (Join-Path $src.FullName "trading-shorts-bot\*") $dest -Recurse -Force
Remove-Item $zip, $tmp -Recurse -Force
& (Join-Path $dest ".venv\Scripts\python.exe") -m pip install -q -r (Join-Path $dest "requirements.txt")
Write-Output "updated - close and reopen the AiAlgobot app"
