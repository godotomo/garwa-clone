# Termux Browser Pilot — Panduan Praktis (terverifikasi 2026-09)

Panduan penggunaan `termux-browser-pilot` (`tbp`) untuk automasi browser sungguhan di Termux, termasuk menembus Cloudflare Turnstile. Terverifikasi berhasil di 9inference.cloud (registrasi 3-langkah berjalan normal tanpa blokir Turnstile).

## 1. Setup (sekali saja)

```bash
# 1. Tambah repo x11 + tur (menyediakan Firefox/Chromium)
pkg install -y x11-repo tur-repo

# 2. Install Firefox + Xvfb + tools otomasi
pkg install -y firefox xorg-server-xvfb xdotool xclip openbox imagemagick python3 ca-certificates

# 3. Clone termux-browser-pilot (TIDAK ada di PyPI)
git clone https://github.com/salviz/termux-browser-pilot.git
cd termux-browser-pilot

# 4. Buat wrapper `tbp` manual (karena pip build isolation rusak di Termux py3.14)
cat > $PREFIX/bin/tbp <<'EOF'
#!/usr/bin/env bash
export PYTHONPATH="/data/data/com.termux/files/home/garwa-coder-v2/termux-browser-pilot${PYTHONPATH:+:$PYTHONPATH}"
exec python3 /data/data/com.termux/files/home/garwa-coder-v2/termux-browser-pilot/cli.py "$@"
EOF
chmod +x $PREFIX/bin/tbp

# Verifikasi
tbp --version   # → tbp 0.1.0a1
```

> **Catatan pip:** `pip install .` gagal di Termux Python 3.14 karena modul `pip._internal.operations.install.wheel` hilang. Jangan coba perbaiki pip — pakai wrapper manual di atas.

## 2. Siklus hidup daemon

```bash
tbp start          # mulai daemon (otomatis start Xvfb :99 + openbox + Firefox)
tbp status         # PID, browser, URL, uptime
tbp stop           # matikan daemon
```

- Daemon otomatis mengelola Xvfb (display `:99`, 1920x1080x24), membersihkan stale lock file, dan memulai openbox.
- `DISPLAY` di-set otomatis oleh daemon — tidak perlu export manual.

## 3. Perintah inti

| Perintah | Fungsi |
|----------|--------|
| `tbp goto URL [-cf]` | Navigasi; `-cf` = Cloudflare bypass |
| `tbp text [--selector S]` | Baca teks tampak halaman |
| `tbp html [--selector S]` | Baca HTML |
| `tbp eval "JS"` | Jalankan JavaScript, kembalikan hasil |
| `tbp find "Teks" [--role R]` | Cari elemen interaktif by text |
| `tbp click SELECTOR [--human]` | Klik elemen (`--human` = gerakan Bezier) |
| `tbp type SELECTOR TEXT` | Ketik ke input |
| `tbp press KEY` | Tekan tombol (Enter, Tab, Esc...) |
| `tbp iframe list` | Daftar iframe (deteksi Turnstile) |
| `tbp cookies --save f.json` / `--load` | Simpan/muat sesi |
| `tbp screenshot PATH [--full]` | Screenshot |
| `tbp scroll [--up] [--amount N]` | Scroll |
| `tbp a11y` | Accessibility tree (ARIA roles) |
| `tbp links [--limit N]` | Daftar link |

Semua perintah mendukung `--json` untuk output terstruktur (AI-friendly).

## 4. Workflow menembus Cloudflare Turnstile

```bash
# 1. Mulai daemon
tbp start

# 2. Buka target dengan flag Cloudflare
tbp goto "https://target.com/register" -cf

# 3. Pastikan halaman TERMUAT PENUH (bukan challenge)
tbp text   # harus berisi konten asli, bukan "Verify you are human"

# 4. Deteksi widget Turnstile
tbp iframe list
tbp eval "typeof turnstile !== 'undefined' ? 'loaded' : 'not loaded'"
tbp eval "document.querySelector('[name=cf-turnstile-response]') ? 'ada' : 'tidak'"

# 5. Isi form + submit (widget Turnstile ter-render setelah interaksi)
tbp type "input#email" "akun@email.com"
tbp find "Kirim Kode"          # cari tombol
tbp click "selector-tombol"

# 6. Verifikasi lanjut ke step berikutnya
tbp text   # mis. "Kode verifikasi sudah dikirim ke ..."
```

**Poin penting:**
- Browser sungguhan (Firefox via Xvfb) **menyelesaikan Turnstile otomatis** — tidak perlu solver manual.
- `-cf` flag memakai mode Cloudflare bypass (Firefox TLS fingerprint).
- Widget Turnstile (`cf-turnstile-response`) sering baru muncul setelah interaksi/submit pertama.

## 5. Verifikasi email / OTP

1. **Gunakan email yang bisa Anda baca inbox-nya** saat registrasi (mis. akun IMAP yang Anda akses via `read_inbox`). Jangan pakai email acak yang tak bisa diakses.
2. Baca OTP/verifikasi dari inbox, lalu masukkan ke form via `tbp type`.
3. Atau klik link verifikasi via `tbp goto <link>`.

## 6. Troubleshooting

| Masalah | Solusi |
|---------|--------|
| `tbp` tidak ditemukan | Wrapper belum dibuat / PYTHONPATH salah |
| `Error: No daemon running` | Jalankan `tbp start` dulu |
| `JS error: ... is null` | Halaman berubah/navigasi; cek `tbp status` + `tbp text` dulu |
| Turnstile tidak ter-render | Isi form & submit dulu; cek `tbp iframe list` |
| Xvfb lock file | Daemon otomatis membersihkannya di `_start_xvfb()` |
| Halaman challenge Cloudflare | Pastikan pakai `-cf` dan browser Firefox (bukan text browser) |

## 7. Batasan

- **Tidak ada `pip install`** — pakai wrapper manual.
- **Chromium** butuh `websockets` (mode CDP) dan jauh lebih berat (~570–640MB) — prefer Firefox.
- Turnstile tetap menolak **datacenter IP**; browser di perangkat fisik (termasuk Termux Android) memakai IP perangkat asli → lolos.
- Browser teks (`lynx`/`w3m`/`links`) TIDAK bisa menembus Turnstile.
