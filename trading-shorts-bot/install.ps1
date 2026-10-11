# One-step install (or re-install) of the AiAlgobot app on Windows.
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/topfan2026/journal/claude/inspiring-lamport-eg0e2u/trading-shorts-bot/install.ps1 | iex"
# It puts the bot in  C:\Users\<you>\AiAlgobot , sets up Python for it, makes the desktop icon and opens the app.
# Your settings (.env) are never touched if the folder already exists, so it is safe to run again.
$ErrorActionPreference = "Stop"
$branch = "claude/inspiring-lamport-eg0e2u"
$url = "https://github.com/topfan2026/journal/archive/refs/heads/$branch.zip"
$dest = Join-Path $env:USERPROFILE "AiAlgobot"
$zip = Join-Path $env:TEMP "aialgobot-install.zip"
$tmp = Join-Path $env:TEMP "aialgobot-install"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# 1. Python
$py = $null
foreach ($name in @("python", "py")) { $c = Get-Command $name -ErrorAction SilentlyContinue; if ($c) { $py = $c.Source; break } }
if (-not $py) { Write-Output "Python is not installed. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again."; return }
& $py -c "import tkinter" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Output "This Python has no Tkinter. Re-run the Python installer, choose Modify, and tick 'tcl/tk and IDLE'. Then run this again."; return }

# 2. Download the latest bot and copy it in (existing settings are kept)
Write-Output "downloading the latest bot..."
Invoke-WebRequest $url -OutFile $zip -UseBasicParsing
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive $zip -DestinationPath $tmp -Force
$src = Get-ChildItem $tmp -Directory | Select-Object -First 1
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$keep = Join-Path $dest ".env"
$saved = $null
if (Test-Path $keep) { $saved = Get-Content $keep -Raw }
Copy-Item (Join-Path $src.FullName "trading-shorts-bot\*") $dest -Recurse -Force
if ($saved -ne $null) { Set-Content -Path $keep -Value $saved -NoNewline }
Remove-Item $zip, $tmp -Recurse -Force

# 3. Python packages for the bot
$venvPy = Join-Path $dest ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { Write-Output "setting up Python for the bot..."; & $py -m venv (Join-Path $dest ".venv") }
Write-Output "installing the bot's packages (a few minutes)..."
& $venvPy -m pip install -q --upgrade pip
& $venvPy -m pip install -q -r (Join-Path $dest "requirements.txt")

# 4. Desktop icon
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "AiAlgobot.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = Join-Path $dest ".venv\Scripts\pythonw.exe"
$s.Arguments = '"' + (Join-Path $dest "live_gui.py") + '"'
$s.WorkingDirectory = $dest
$s.IconLocation = (Join-Path $dest "assets\app.ico") + ",0"
$s.Description = "AiAlgobot - live stream and trading bot"
$s.Save()

Write-Output "done. The AiAlgobot icon is on your desktop. Opening it now..."
Start-Process -FilePath (Join-Path $dest ".venv\Scripts\pythonw.exe") -ArgumentList ('"' + (Join-Path $dest "live_gui.py") + '"') -WorkingDirectory $dest
