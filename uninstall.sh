#!/usr/bin/env bash
#
# uninstall.sh -- menghapus instalasi Garwa CLI
#
# Menghapus artefak yang dibuat install.sh:
#   - launcher `garwa` di ~/.local/bin (atau folder --prefix yang dipakai)
#   - virtualenv garwa/.venv di dalam repo (opsional, dengan --purge)
#
# Pemakaian:
#   ./uninstall.sh                 # hapus launcher saja (venv dibiarkan)
#   ./uninstall.sh --purge         # hapus launcher + hapus folder .venv
#   ./uninstall.sh --prefix DIR    # hapus launcher dari folder selain default
#   ./uninstall.sh -y              # tanpa konfirmasi
#
# Catatan: script ini TIDAK menyentuh dependency yang terinstall ke Python
# sistem (kalau dulu dipasang dengan --no-venv), dan tidak menghapus database
# sesi (*.db) milik Anda.

set -euo pipefail

# --- Lokasi repo (folder tempat uninstall.sh berada) -------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"

# --- Konfigurasi default ------------------------------------------------------
PREFIX="${HOME}/.local/bin"
PURGE=0
ASSUME_YES=0

usage() {
    awk 'NR>1 && NR<=40 && /^#/ { sub(/^# ?/, ""); print } NR>1 && NR<=40 && !/^#/ && $0!="" { exit }' "$0"
    echo ""
    echo "Opsi:"
    echo "  --prefix DIR    folder launcher 'garwa' yang mau dihapus (default: ~/.local/bin)"
    echo "  --purge         sekalian hapus folder virtualenv .venv di repo"
    echo "  -y, --yes       jangan minta konfirmasi"
    echo "  -h, --help      tampilkan bantuan ini"
}

# --- Parse argumen ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)
            PREFIX="$2"; shift 2;;
        --purge)
            PURGE=1; shift;;
        -y|--yes)
            ASSUME_YES=1; shift;;
        -h|--help)
            usage; exit 0;;
        *)
            echo "Opsi tidak dikenal: $1" >&2
            usage >&2; exit 1;;
    esac
done

LAUNCHER_PATH="$PREFIX/garwa"
VENV_DIR="$REPO_ROOT/.venv"

# --- Ringkasan yang akan dihapus ---------------------------------------------
echo "Akan menghapus instalasi Garwa:"
echo "  - Launcher : $LAUNCHER_PATH"
if [[ "$PURGE" == "1" ]]; then
    echo "  - Virtualenv: $VENV_DIR"
else
    echo "  - Virtualenv: (dibiarkan -- gunakan --purge untuk menghapus)"
fi
echo ""

if [[ "$ASSUME_YES" != "1" ]]; then
    read -r -p "Lanjutkan? [y/N] " ans
    case "$ans" in
        y|Y|yes|YES) ;;
        *) echo "Dibatalkan."; exit 0;;
    esac
fi

# --- Hapus launcher -----------------------------------------------------------
if [[ -e "$LAUNCHER_PATH" ]]; then
    rm -f "$LAUNCHER_PATH"
    echo "  [ok] Launcher dihapus: $LAUNCHER_PATH"
else
    echo "  [..] Launcher tidak ditemukan: $LAUNCHER_PATH (dilewati)"
fi

# --- Hapus venv (opsional) ----------------------------------------------------
if [[ "$PURGE" == "1" && -d "$VENV_DIR" ]]; then
    rm -rf "$VENV_DIR"
    echo "  [ok] Virtualenv dihapus: $VENV_DIR"
elif [[ "$PURGE" == "1" ]]; then
    echo "  [..] Virtualenv tidak ditemukan: $VENV_DIR (dilewati)"
fi

echo ""
echo "Selesai. Perintah 'garwa' sudah tidak bisa dipanggil lagi."
echo "Database sesi (*.db) dan folder skills tidak dihapus."
