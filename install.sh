#!/usr/bin/env bash
#
# install.sh -- instalasi Garwa CLI
#
# Membuat perintah `garwa` yang bisa dipanggil dari folder mana pun (workdir =
# folder tempat Anda menjalankannya), dengan cara:
#
#   1. Membuat virtualenv terisolasi di dalam repo (garwa/.venv) supaya
#      dependency tidak mengotori Python sistem.
#   2. Menginstal dependency dari requirements.txt ke venv tersebut.
#   3. Membuat launcher `garwa` di ~/.local/bin (atau folder yang Anda pilih
#      lewat --prefix) yang memanggil venv python + garwa_cli.py.
#
# Pemakaian:
#   ./install.sh                 # instal default (venv + launcher di ~/.local/bin)
#   ./install.sh --prefix DIR    # taruh launcher di DIR (harus ada di PATH)
#   ./install.sh --no-venv       # pakai python3 sistem, tanpa venv
#   ./install.sh --uninstall     # hapus launcher (dan venv dengan --purge)
#   ./install.sh --purge         # hapus launcher + venv
#
# Setelah instal, pastikan folder launcher ada di PATH, lalu jalankan:
#   garwa --help
#   garwa --workdir "$PWD"   # (opsional; sebenarnya sudah default ke folder saat ini)

set -euo pipefail

# --- Lokasi repo (folder tempat install.sh berada) ---------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
PYTHON_BIN="${PYTHON:-python3}"

# --- Konfigurasi default ------------------------------------------------------
PREFIX="${HOME}/.local/bin"
USE_VENV=1
UNINSTALL=0
PURGE=0

usage() {
    # Tampilkan blok komentar header (baris yang diawali '#') dari file ini,
    # melewati shebang (baris 1) dan baris kosong.
    awk 'NR>1 && NR<=40 && /^#/ { sub(/^# ?/, ""); print } NR>1 && NR<=40 && !/^#/ && $0!="" { exit }' "$0"
    echo ""
    echo "Opsi:"
    echo "  --prefix DIR    folder tempat launcher 'garwa' dibuat (default: ~/.local/bin)"
    echo "  --no-venv       jangan buat venv; pakai python3 sistem"
    echo "  --uninstall     hapus launcher 'garwa' saja"
    echo "  --purge         hapus launcher 'garwa' + folder venv"
    echo "  -h, --help      tampilkan bantuan ini"
}

# --- Parse argumen ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)
            PREFIX="$2"; shift 2;;
        --no-venv)
            USE_VENV=0; shift;;
        --uninstall)
            UNINSTALL=1; shift;;
        --purge)
            UNINSTALL=1; PURGE=1; shift;;
        -h|--help)
            usage; exit 0;;
        *)
            echo "Opsi tidak dikenal: $1" >&2
            usage >&2; exit 1;;
    esac
done

VENV_DIR="$REPO_ROOT/.venv"
LAUNCHER_PATH="$PREFIX/garwa"

# --- Uninstall ----------------------------------------------------------------
if [[ "$UNINSTALL" == "1" ]]; then
    if [[ -e "$LAUNCHER_PATH" ]]; then
        rm -f "$LAUNCHER_PATH"
        echo "  [ok] Launcher dihapus: $LAUNCHER_PATH"
    else
        echo "  [..] Launcher tidak ditemukan: $LAUNCHER_PATH"
    fi
    if [[ "$PURGE" == "1" && -d "$VENV_DIR" ]]; then
        rm -rf "$VENV_DIR"
        echo "  [ok] Venv dihapus: $VENV_DIR"
    fi
    echo "Selesai."
    exit 0
fi

# --- Validasi awal ------------------------------------------------------------
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ERROR: '$PYTHON_BIN' tidak ditemukan di PATH." >&2
    exit 1
fi

# --- Cek versi Python minimal 3.10 -------------------------------------------
PYTHON_MAJOR="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.major)' 2>/dev/null)"
PYTHON_MINOR="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null)"
if [[ -z "$PYTHON_MAJOR" || -z "$PYTHON_MINOR" ]]; then
    echo "ERROR: Tidak dapat mendeteksi versi '$PYTHON_BIN'." >&2
    exit 1
fi
if [[ "$PYTHON_MAJOR" -lt 3 ]] || { [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 10 ]]; }; then
    echo "ERROR: Dibutuhkan Python >= 3.10, tetapi ditemukan Python $PYTHON_MAJOR.$PYTHON_MINOR." >&2
    echo "       Silakan upgrade Python atau gunakan path Python lain dengan:" >&2
    echo "         PYTHON=python3.12 ./install.sh" >&2
    exit 1
fi
echo "  [ok] Python $PYTHON_MAJOR.$PYTHON_MINOR terdeteksi (minimal 3.10 terpenuhi)"
if [[ ! -f "$REPO_ROOT/garwa_cli.py" ]]; then
    echo "ERROR: garwa_cli.py tidak ditemukan di $REPO_ROOT." >&2
    echo "       Pastikan install.sh dijalankan dari root repo Garwa." >&2
    exit 1
fi
if [[ ! -f "$REPO_ROOT/requirements.txt" ]]; then
    echo "ERROR: requirements.txt tidak ditemukan di $REPO_ROOT." >&2
    exit 1
fi

# --- Siapkan folder launcher --------------------------------------------------
if [[ ! -d "$PREFIX" ]]; then
    mkdir -p "$PREFIX"
    echo "  [ok] Membuat folder launcher: $PREFIX"
fi

# --- Siapkan Python yang dipakai ---------------------------------------------
if [[ "$USE_VENV" == "1" ]]; then
    echo "==> Menyiapkan virtualenv di $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    VENV_PYTHON="$VENV_DIR/bin/python"
    VENV_PIP="$VENV_DIR/bin/pip"
    if [[ ! -x "$VENV_PYTHON" ]]; then
        echo "ERROR: gagal membuat venv (python -m venv)." >&2
        echo "       Coba install dengan --no-venv, atau install 'python3-venv'." >&2
        exit 1
    fi
    echo "==> Menginstal dependency ke venv"
    "$VENV_PIP" install --upgrade pip >/dev/null
    "$VENV_PIP" install -r "$REPO_ROOT/requirements.txt"
    RUNNER="$VENV_PYTHON"
else
    echo "==> Mode --no-venv: memakai $PYTHON_BIN sistem"
    RUNNER="$PYTHON_BIN"
fi

# --- Tulis launcher -----------------------------------------------------------
cat > "$LAUNCHER_PATH" <<EOF
#!/usr/bin/env bash
# Launcher Garwa -- dibuat otomatis oleh install.sh. Jangan edit manual.
# Menjalankan garwa dengan workdir = folder tempat perintah ini dipanggil.
REPO_ROOT="$REPO_ROOT"
RUNNER="$RUNNER"
exec "\$RUNNER" "\$REPO_ROOT/garwa_cli.py" --workdir "\$PWD" "\$@"
EOF
chmod +x "$LAUNCHER_PATH"
echo "  [ok] Launcher dibuat: $LAUNCHER_PATH"

# --- Pastikan PREFIX ada di PATH (persisten) ----------------------------------
# Menambahkan '$PREFIX' ke PATH sesi berjalan DAN ke file profile shell
# (mis. ~/.zshrc di macOS) supaya tetap berlaku setelah terminal di-restart.
ensure_prefix_in_path() {
    # 1) PATH sesi berjalan
    if [[ ":$PATH:" != *":$PREFIX:"* ]]; then
        export PATH="$PREFIX:$PATH"
        echo "  [ok] '$PREFIX' ditambahkan ke PATH sesi ini."
    fi

    # 2) Deteksi file profile shell yang tepat.
    local profile_file=""
    local shell_name
    shell_name="$(basename "${SHELL:-}")"
    case "$shell_name" in
        zsh)
            profile_file="${ZDOTDIR:-$HOME}/.zshrc"
            ;;
        bash)
            if [[ -f "$HOME/.bash_profile" ]]; then
                profile_file="$HOME/.bash_profile"
            else
                profile_file="$HOME/.bashrc"
            fi
            ;;
        *)
            profile_file="$HOME/.profile"
            ;;
    esac

    if [[ -z "$profile_file" ]]; then
        echo "  [..] Tidak dapat mendeteksi shell profile. Tambahkan manual ke shell profile Anda:"
        echo "       export PATH=\"$PREFIX:\$PATH\""
        return 0
    fi

    # 3) Tambahkan baris export bila belum ada di profile.
    if grep -qF "$PREFIX" "$profile_file" 2>/dev/null; then
        echo "  [ok] '$PREFIX' sudah terdaftar di $profile_file"
    else
        # Pastikan file profile ada (buat bila belum).
        if [[ ! -f "$profile_file" ]]; then
            touch "$profile_file" 2>/dev/null || { echo "  [..] Tidak bisa membuat $profile_file."; return 0; }
        fi
        if printf '\n# Ditambahkan oleh install.sh Garwa\n%s\n' "export PATH=\"$PREFIX:\$PATH\"" >> "$profile_file" 2>/dev/null; then
            echo "  [ok] Menambahkan 'export PATH=\"$PREFIX:\$PATH\"' ke $profile_file"
            echo "       (berlaku penuh setelah Anda membuka terminal baru)"
        else
            echo "  [..] Gagal menulis ke $profile_file. Tambahkan manual:"
            echo "       export PATH=\"$PREFIX:\$PATH\""
        fi
    fi
}

# --- Verifikasi ---------------------------------------------------------------
echo ""
echo "==> Verifikasi instalasi"
if "$RUNNER" -c "import sys; sys.path.insert(0, '$REPO_ROOT'); import garwa; print('  garwa version:', garwa.__version__)" 2>/dev/null; then
    :
else
    echo "  (impor garwa gagal -- mungkin dependency belum lengkap, tapi launcher tetap dibuat.)"
fi

echo ""
echo "Instalasi selesai. Memastikan '$PREFIX' ada di PATH..."
ensure_prefix_in_path
echo ""
echo "Coba jalankan dari folder mana pun:"
echo "    garwa --help"
echo "    garwa --workdir \"\$PWD\""
