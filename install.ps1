#Requires -Version 5.1
<#
================================================================================
 install.ps1 -- instalasi Garwa CLI untuk Windows (PowerShell)
================================================================================

Membuat perintah `garwa` yang bisa dipanggil dari folder mana pun (workdir =
folder tempat Anda menjalankannya), dengan cara:

  1. Membuat virtualenv terisolasi di dalam repo (garwa\.venv) supaya
     dependency tidak mengotori Python sistem.
  2. Menginstal dependency dari requirements.txt ke venv tersebut.
  3. Membuat launcher `garwa` (garwa.cmd + garwa.ps1) di folder yang Anda
     pilih (default: %USERPROFILE%\.local\bin) yang memanggil venv python
     + garwa_cli.py, lalu menambahkan folder itu ke PATH user.

Pemakaian (dari PowerShell, di root repo):
  .\install.ps1                  # instal default (venv + launcher di ~\.local\bin)
  .\install.ps1 -Prefix DIR      # taruh launcher di DIR (akan ditambah ke PATH)
  .\install.ps1 -NoVenv          # pakai python sistem, tanpa venv
  .\install.ps1 -Uninstall       # hapus launcher (dan venv dengan -Purge)
  .\install.ps1 -Purge           # hapus launcher + venv
  .\install.ps1 -Python py -3.12 # pakai interpreter Python tertentu

Setelah instal, buka terminal baru lalu jalankan:
  garwa --help
  garwa --workdir "$PWD"   # (opsional; sebenarnya sudah default ke folder saat ini)

Catatan: jalankan dari PowerShell. Kalau kebijakan eksekusi menolak, jalankan
sekali:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
================================================================================
#>

[CmdletBinding()]
param(
    [string]$Prefix,
    [switch]$NoVenv,
    [switch]$Uninstall,
    [switch]$Purge,
    [string]$Python = "python",
    [switch]$Help
)

$ErrorActionPreference = "Stop"

function Write-Usage {
    Get-Content -LiteralPath $PSCommandPath |
        Where-Object { $_ -match '^\s*#' -and $_ -notmatch '^#Requires' } |
        ForEach-Object { $_.Substring($_.IndexOf('#') + 1).TrimStart(' ') }
}

if ($Help) {
    Write-Usage
    exit 0
}

# --- Lokasi repo (folder tempat install.ps1 berada) ---------------------------
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)

# --- Konfigurasi default ------------------------------------------------------
if (-not $Prefix) { $Prefix = Join-Path $HOME ".local\bin" }
$VenvDir = Join-Path $RepoRoot ".venv"

# --- Uninstall ----------------------------------------------------------------
if ($Uninstall) {
    # Launcher yang mungkin dibuat: garwa.cmd dan garwa.ps1
    foreach ($name in @("garwa.cmd", "garwa.ps1")) {
        $launcher = Join-Path $Prefix $name
        if (Test-Path -LiteralPath $launcher) {
            Remove-Item -LiteralPath $launcher -Force
            Write-Host "  [ok] Launcher dihapus: $launcher"
        } else {
            Write-Host "  [..] Launcher tidak ditemukan: $launcher"
        }
    }
    if ($Purge -and (Test-Path -LiteralPath $VenvDir)) {
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
        Write-Host "  [ok] Venv dihapus: $VenvDir"
    } elseif ($Purge) {
        Write-Host "  [..] Venv tidak ditemukan: $VenvDir"
    }
    Write-Host "Selesai."
    exit 0
}

# --- Validasi awal ------------------------------------------------------------
$py = Get-Command $Python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "ERROR: '$Python' tidak ditemukan di PATH." -ForegroundColor Red
    exit 1
}
$pyPath = $py.Source

# --- Cek versi Python minimal 3.10 -------------------------------------------
try {
    $verInfo = & $pyPath -c "import sys; print('%d.%d' % sys.version_info[:2])"
} catch {
    Write-Host "ERROR: Tidak dapat mendeteksi versi '$Python'." -ForegroundColor Red
    exit 1
}
$verParts = $verInfo.Trim() -split '\.'
$major = [int]$verParts[0]
$minor = [int]$verParts[1]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
    Write-Host "ERROR: Dibutuhkan Python >= 3.10, tetapi ditemukan Python $major.$minor." -ForegroundColor Red
    Write-Host "       Silakan upgrade Python atau gunakan interpreter lain dengan:" -ForegroundColor Red
    Write-Host "         .\install.ps1 -Python py -3.12" -ForegroundColor Red
    exit 1
}
Write-Host "  [ok] Python $major.$minor terdeteksi (minimal 3.10 terpenuhi)"

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "garwa_cli.py"))) {
    Write-Host "ERROR: garwa_cli.py tidak ditemukan di $RepoRoot." -ForegroundColor Red
    Write-Host "       Pastikan install.ps1 dijalankan dari root repo Garwa." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "requirements.txt"))) {
    Write-Host "ERROR: requirements.txt tidak ditemukan di $RepoRoot." -ForegroundColor Red
    exit 1
}

# --- Siapkan folder launcher --------------------------------------------------
if (-not (Test-Path -LiteralPath $Prefix)) {
    New-Item -ItemType Directory -Path $Prefix -Force | Out-Null
    Write-Host "  [ok] Membuat folder launcher: $Prefix"
}

# --- Siapkan Python yang dipakai ---------------------------------------------
if ($NoVenv) {
    Write-Host "==> Mode -NoVenv: memakai $pyPath sistem"
    $Runner = $pyPath
} else {
    Write-Host "==> Menyiapkan virtualenv di $VenvDir"
    & $pyPath -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: gagal membuat venv (python -m venv)." -ForegroundColor Red
        Write-Host "       Coba instal dengan -NoVenv, atau pastikan modul venv tersedia." -ForegroundColor Red
        exit 1
    }
    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Host "ERROR: venv dibuat tapi python.exe tidak ditemukan di $VenvDir." -ForegroundColor Red
        exit 1
    }
    Write-Host "==> Menginstal dependency ke venv"
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { exit 1 }
    & $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) { exit 1 }
    $Runner = $VenvPython
}

# --- Tulis launcher -----------------------------------------------------------
# garwa.cmd  -> dipanggil dari cmd.exe dan PowerShell (paling portabel).
# garwa.ps1  -> dipanggil dari PowerShell; mewarisi konteks PowerShell.
$cmdContent = @"
@echo off
rem Launcher Garwa -- dibuat otomatis oleh install.ps1. Jangan edit manual.
rem Menjalankan garwa dengan workdir = folder tempat perintah ini dipanggil.
set "REPO_ROOT=$RepoRoot"
set "RUNNER=$Runner"
"%RUNNER%" "%REPO_ROOT%\garwa_cli.py" --workdir "%CD%" %*
"@
$cmdLauncher = Join-Path $Prefix "garwa.cmd"
Set-Content -LiteralPath $cmdLauncher -Value $cmdContent -Encoding ASCII
Write-Host "  [ok] Launcher dibuat: $cmdLauncher"

$psContent = @"
# Launcher Garwa -- dibuat otomatis oleh install.ps1. Jangan edit manual.
# Menjalankan garwa dengan workdir = folder tempat perintah ini dipanggil.
`$RepoRoot = "$RepoRoot"
`$Runner = "$Runner"
& `$Runner "`$RepoRoot\garwa_cli.py" --workdir (Get-Location).Path @args
exit `$LASTEXITCODE
"@
$psLauncher = Join-Path $Prefix "garwa.ps1"
Set-Content -LiteralPath $psLauncher -Value $psContent -Encoding UTF8
Write-Host "  [ok] Launcher dibuat: $psLauncher"

# --- Tambahkan folder launcher ke PATH user -----------------------------------
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
$inPath = ($userPath -split ';' | Where-Object { $_ -and $_.TrimEnd('\') -eq $Prefix.TrimEnd('\') }) -ne $null
if (-not $inPath) {
    $newPath = if ($userPath) { "$userPath;$Prefix" } else { $Prefix }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "  [ok] Folder launcher ditambahkan ke PATH user: $Prefix"
    Write-Host "       (Buka terminal BARU agar perubahan PATH berlaku.)"
} else {
    Write-Host "  [..] Folder launcher sudah ada di PATH user."
}

# --- Verifikasi ---------------------------------------------------------------
Write-Host ""
Write-Host "==> Verifikasi instalasi"
$verifyCode = "import sys; sys.path.insert(0, r'$RepoRoot'); import garwa; print('  garwa version:', garwa.__version__)"
$verifyOut = & $Runner -c $verifyCode 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host $verifyOut
} else {
    Write-Host "  (impor garwa gagal -- mungkin dependency belum lengkap, tapi launcher tetap dibuat.)"
}

Write-Host ""
Write-Host "Instalasi selesai. Buka terminal BARU lalu coba dari folder mana pun:"
Write-Host "    garwa --help"
Write-Host "    garwa --workdir `"`$PWD`""
