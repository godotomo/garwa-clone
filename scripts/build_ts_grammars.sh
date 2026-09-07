#!/usr/bin/env bash
# build_ts_grammars.sh
# Build grammar tree-sitter individual dari source GitHub untuk Termux/Android.
# Mengapa: tree-sitter-language-pack (.abi3.so) sering gagal dimuat atau panic
# rustls-platform-verifier di Termux. Grammar individual yang di-build dari
# source (non-abi3, tanpa hide-symbols) berfungsi andal.
#
# Penggunaan: bash scripts/build_ts_grammars.sh [python javascript ...]
# (default: python javascript typescript c cpp java go rust)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${TMPDIR:-/tmp}/ts-grammars"
WHEEL_DIR="$ROOT/.ts-wheels"
mkdir -p "$BUILD_DIR" "$WHEEL_DIR"

# mapping: nama grammar -> repo GitHub (owner/repo) -> tag
# tag kosong = pakai HEAD
declare -A REPO=(
  [python]="tree-sitter/tree-sitter-python"
  [javascript]="tree-sitter/tree-sitter-javascript"
  [typescript]="tree-sitter/tree-sitter-typescript"
  [c]="tree-sitter/tree-sitter-c"
  [cpp]="tree-sitter/tree-sitter-cpp"
  [java]="tree-sitter/tree-sitter-java"
  [go]="tree-sitter/tree-sitter-go"
  [rust]="tree-sitter/tree-sitter-rust"
)
declare -A TAG=(
  [python]="v0.25.0"
  [javascript]="v0.23.1"
  [typescript]="v0.23.2"
  [c]="v0.23.5"
  [cpp]="v0.23.4"
  [java]="v0.23.5"
  [go]="v0.23.4"
  [rust]="v0.23.2"
)

LANGS=("$@")
if [ ${#LANGS[@]} -eq 0 ]; then
  LANGS=(python javascript typescript c cpp java go rust)
fi

build_one() {
  local lang="$1"
  local repo="${REPO[$lang]:-}"
  local tag="${TAG[$lang]:-}"
  if [ -z "$repo" ]; then
    echo "[skip] $lang: tidak ada mapping repo"
    return
  fi
  local dir="$BUILD_DIR/$lang"
  echo "=== build $lang ($repo ${tag:-HEAD}) ==="
  rm -rf "$dir"
  if [ -n "$tag" ]; then
    git clone --depth 1 --branch "$tag" "https://github.com/$repo" "$dir" 2>/dev/null || {
      git clone --depth 1 "https://github.com/$repo" "$dir" 2>/dev/null || { echo "[fail] clone $lang"; return; }
    }
  else
    git clone --depth 1 "https://github.com/$repo" "$dir" 2>/dev/null || { echo "[fail] clone $lang"; return; }
  fi
  if [ ! -f "$dir/setup.py" ]; then
    echo "[skip] $lang: tidak ada setup.py (mungkin bukan paket python)"
    return
  fi
  # patch setup.py: non-abi3, tanpa hide-symbols, tanpa fvisibility=hidden
  sed -i 's/ext.extra_compile_args = \["-std=c11", "-fvisibility=hidden"\]/ext.extra_compile_args = ["-std=c11"]/' "$dir/setup.py" 2>/dev/null || true
  sed -i 's/("TREE_SITTER_HIDE_SYMBOLS", None),//' "$dir/setup.py" 2>/dev/null || true
  sed -i 's/py_limited_api=not get_config_var("Py_GIL_DISABLED")/py_limited_api=False/' "$dir/setup.py" 2>/dev/null || true
  # build wheel & install
  ( cd "$dir" && pip wheel . --no-deps -w "$WHEEL_DIR" >/dev/null 2>&1 ) && {
    # pilih wheel yang nama modulnya cocok dengan bahasa ini (bukan head -1,
    # karena beberapa grammar bisa menghasilkan nama yang mirip, mis. c vs cpp).
    local whl
    whl="$(ls "$WHEEL_DIR"/tree_sitter_${lang}-*.whl 2>/dev/null | head -1)"
    if [ -n "$whl" ]; then
      pip install --force-reinstall --no-deps "$whl" >/dev/null 2>&1 && \
        echo "[ok] $lang terinstall: $(basename "$whl")" || echo "[fail] install $lang"
    else
      echo "[fail] $lang: wheel tidak dihasilkan"
    fi
  } || echo "[fail] build $lang"
}

for lang in "${LANGS[@]}"; do
  build_one "$lang"
done
echo "=== selesai ==="
