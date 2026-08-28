#Requires -Version 5.1
<#
================================================================================
 uninstall.ps1 -- menghapus instalasi Garwa CLI untuk Windows (PowerShell)
================================================================================

Menghapus artefak yang dibuat install.ps1:
  - launcher `garwa` (garwa.cmd + garwa.ps1) di folder launcher
  - virtualenv garwa\.venv di dalam repo (opsional, dengan -Purge)
  - (opsional) folder launcher dari PATH user

Pemakaian:
  .\uninstall.ps1                  # hapus launcher saja (venv dibiarkan)
  .\uninstall.ps1 -Purge           # hapus launcher + hapus folder .venv
  .\uninstall.ps1 -Prefix DIR      # hapus launcher dari folder selain default
  .\uninstall.ps1 -RemoveFromPath  # sekalian hapus folder launcher dari PATH user
  .\uninstall.ps1 -Yes             # tanpa konfirmasi

Catatan: script ini TIDAK menyentuh dependency yang terinstall ke Python
sistem (kalau dulu dipasang dengan -NoVenv), dan tidak menghapus database
sesi (*.db) milik Anda.
================================================================================
#>

[CmdletBinding()]
param(
    [string]$Prefix,
    [switch]$Purge,
    [switch]$RemoveFromPath,
    [switch]$Yes,
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

# --- Lokasi repo (folder tempat uninstall.ps1 berada) -------------------------
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)

# --- Konfigurasi default ------------------------------------------------------
if (-not $Prefix) { $Prefix = Join-Path $HOME ".local\bin" }
$VenvDir = Join-Path $RepoRoot ".venv"

# --- Ringkasan yang akan dihapus ---------------------------------------------
Write-Host "Akan menghapus instalasi Garwa:"
Write-Host "  - Launcher : $Prefix\garwa.cmd"
Write-Host "  - Launcher : $Prefix\garwa.ps1"
if ($Purge) {
    Write-Host "  - Virtualenv: $VenvDir"
} else {
    Write-Host "  - Virtualenv: (dibiarkan -- gunakan -Purge untuk menghapus)"
}
if ($RemoveFromPath) {
    Write-Host "  - PATH user : folder '$Prefix' akan dihapus dari PATH"
}
Write-Host ""

if (-not $Yes) {
    $ans = Read-Host "Lanjutkan? [y/N]"
    if ($ans -notmatch '^(y|yes)$') {
        Write-Host "Dibatalkan."
        exit 0
    }
}

# --- Hapus launcher -----------------------------------------------------------
foreach ($name in @("garwa.cmd", "garwa.ps1")) {
    $launcher = Join-Path $Prefix $name
    if (Test-Path -LiteralPath $launcher) {
        Remove-Item -LiteralPath $launcher -Force
        Write-Host "  [ok] Launcher dihapus: $launcher"
    } else {
        Write-Host "  [..] Launcher tidak ditemukan: $launcher (dilewati)"
    }
}

# --- Hapus venv (opsional) ----------------------------------------------------
if ($Purge -and (Test-Path -LiteralPath $VenvDir)) {
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
    Write-Host "  [ok] Virtualenv dihapus: $VenvDir"
} elseif ($Purge) {
    Write-Host "  [..] Virtualenv tidak ditemukan: $VenvDir (dilewati)"
}

# --- Hapus folder launcher dari PATH user (opsional) --------------------------
if ($RemoveFromPath) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $target = $Prefix.TrimEnd('\')
    $parts = $userPath -split ';' | Where-Object { $_ -and $_.TrimEnd('\') -ne $target }
    $newPath = $parts -join ';'
    if ($newPath -ne $userPath) {
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Host "  [ok] Folder launcher dihapus dari PATH user: $Prefix"
        Write-Host "       (Buka terminal BARU agar perubahan PATH berlaku.)"
    } else {
        Write-Host "  [..] Folder launcher tidak ada di PATH user (dilewati)"
    }
}

Write-Host ""
Write-Host "Selesai. Perintah 'garwa' sudah tidak bisa dipanggil lagi."
Write-Host "Database sesi (*.db) dan folder skills tidak dihapus."
