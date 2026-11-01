$ErrorActionPreference = "Stop"

# EverStickyNote をビルドして dist\ に配布物を作る（このフォルダの .venv の Python で）
#   dist\EverStickyNote\            EverStickyNote.exe、config.toml（config\ から）、README.md、LICENSE、THIRD_PARTY_NOTICES.md
#   dist\EverStickyNote-v<版>.zip    上のフォルダの中身
# 版は src\everstickynote\__init__.py の __version__。
# PyInstaller の作業ファイルは build\ に出す。
# Windows PowerShell 5.1 が日本語のコメントを正しく読むよう、このファイルは BOM 付き UTF-8 で保存する
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw ".venv がありません。py -3.12 -m venv .venv で作ってください。"
}
$Bits = & $Python -c "import struct; print(struct.calcsize('P') * 8)"
if ($Bits -ne "64") {
    throw ".venv の Python が 64-bit ではありません（PySide6 は 64-bit が必要です）。"
}

function Invoke-Checked([string[]]$Arguments) {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "失敗しました: python $($Arguments -join ' ')" }
}

$AppName = "EverStickyNote"
$Assets = Join-Path $ProjectDir "src\everstickynote\assets"

Invoke-Checked @("-m", "pip", "install", "--upgrade", "pyinstaller")
Invoke-Checked @("-m", "pip", "install", "--upgrade", "-r", "requirements.txt")
Invoke-Checked @("-m", "pip", "install", "--no-deps", "-e", ".")
Invoke-Checked @("-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", $AppName, "--paths", "src",
    "--icon", (Join-Path $Assets "app-icon.ico"),
    "--add-data", "$(Join-Path $Assets 'app-icon.png');assets",
    "--distpath", "build\pyinstaller", "--workpath", "build\work", "--specpath", "build",
    "src\everstickynote\__main__.py")

$Version = & $Python -c "import everstickynote; print(everstickynote.__version__)"
if ($LASTEXITCODE -ne 0) { throw "版を読めません" }
$Dist = Join-Path $ProjectDir "dist"
$App = Join-Path $Dist $AppName
if (Test-Path $App) { Remove-Item -Recurse -Force $App }
New-Item -ItemType Directory -Force $App | Out-Null
Copy-Item "build\pyinstaller\$AppName.exe", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md" $App
Copy-Item "config\*" $App

$Zip = Join-Path $Dist "$AppName-v$Version.zip"
if (Test-Path $Zip) { Remove-Item -Force $Zip }
Compress-Archive -Path (Join-Path $App "*") -DestinationPath $Zip
Write-Host "Generated: $App"
Write-Host "Generated: $Zip"
