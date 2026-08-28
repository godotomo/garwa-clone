"""tools/bash_tool.py
Dipecah otomatis dari tools.py (lihat tools/_state.py untuk state bersama).
"""
import os
import sys
import signal
import subprocess

# termios/tty dipakai untuk menyimpan & mengembalikan mode terminal di
# sekitar pemanggilan tool_bash -- jaring pengaman kalau command yang
# dijalankan mengubah mode terminal (mis. stty -echo / raw, program
# interaktif) dan tidak mengembalikannya. Hanya tersedia di POSIX.
try:
    import termios
    _HAS_TERMIOS = True
except ImportError:
    _HAS_TERMIOS = False


try:
    from .. import repo_map as repo_map_mod
except ImportError:
    # repo_map hanya dipakai oleh tool repo_map/outline_file (opsional).
    # Jangan sampai seluruh tools.py (dan cli.py yang meng-import-nya
    # di top-level) gagal start hanya karena modul opsional ini belum ada.
    repo_map_mod = None

try:
    from .. import security as security_mod
except ImportError:
    security_mod = None

try:
    from .. import config as config_mod
except ImportError:
    config_mod = None
from . import _state as state



def _cap_output(text: str, limit: int = state.OUTPUT_CAP_BYTES,
                 head_keep: int = state._OUTPUT_HEAD_KEEP,
                 tail_keep: int = state._OUTPUT_TAIL_KEEP) -> str:
    """Potong teks panjang tapi tetap pertahankan bagian AKHIR.

    Truncate naif (potong dari awal, buang sisanya) akan sering membuang
    justru bagian paling penting: error/traceback/exit message pada output
    command biasanya muncul di baris-baris terakhir. Strategi di sini:
    simpan head_keep byte pertama (konteks command apa yang dijalankan) +
    tail_keep byte terakhir (kemungkinan besar berisi hasil/errornya),
    buang bagian tengah, dan beri penanda eksplisit berapa banyak yang
    dibuang supaya model tahu output ini tidak lengkap (bukan pura-pura
    utuh).
    """
    if len(text) <= limit:
        return text
    omitted = len(text) - head_keep - tail_keep
    return (
        text[:head_keep].rstrip()
        + f"\n\n...[[dipotong -- {omitted} bytes di tengah dihilangkan agar "
          f"tidak membanjiri context window. Bagian akhir output TETAP "
          f"disertakan di bawah karena error/exit code biasanya muncul di "
          f"sana.]]...\n\n"
        + text[-tail_keep:].lstrip()
    )


def _bash_is_risky(arguments: dict):
    """Dipanggil oleh execute_tool() di cli.py untuk memutuskan apakah
    satu pemanggilan tool 'bash' butuh konfirmasi user (destructive dinamis,
    bukan statis seperti tool lain). Lihat catatan di atas _DANGEROUS_BASH_RE.

    Return "force" (bukan True biasa) untuk command yang cocok pola
    berbahaya -- execute_tool() memperlakukan "force" sebagai wajib
    konfirmasi WALAU --auto-approve aktif, karena --auto-approve dimaksudkan
    untuk menghilangkan friksi pada command rutin (baca/edit/jalankan test),
    bukan untuk melewati konfirmasi rm -rf/dd/force-push/dst.
    """
    command = str((arguments or {}).get("command", ""))
    return "force" if state._DANGEROUS_BASH_RE.search(command) else False


def _restore_terminal_mode():
    """Jaring pengaman: kembalikan mode terminal ke mode yang benar setelah
    tool_bash selesai (berhasil, timeout, atau error).

    Kenapa perlu: SEBELUMNYA tool_bash tidak me-redirect stdin, jadi child
    process bash mewarisi stdin terminal utama. Kalau command yang dijalankan
    mengubah mode terminal (mis. `stty -echo`, `stty raw`, program interaktif
    seperti vim/less/top/htop yang memanggil tcsetattr), atau dijalankan di
    background (`&`) dan sempat mengubah mode sebelum kita kill, mode terminal
    utama bisa rusak -- gejala: kursor menghilang & tulisan yang diketik tidak
    terbaca (echo mati / raw mode) setelah tool selesai.

    Fungsi ini menyimpan mode terminal SEBELUM command dijalankan dan
    mengembalikannya SETELAH command selesai, apa pun hasilnya. Ini menutup
    kasus yang tidak bisa dicegah hanya dengan redirect stdin ke DEVNULL
    (mis. child yang membuka /dev/tty secara langsung).

    Hanya aktif di POSIX (termios tersedia) dan hanya kalau stdin memang
    sebuah terminal (sys.stdin.isatty()). Di luar itu no-op.
    """
    if not _HAS_TERMIOS:
        return lambda: None
    try:
        if not sys.stdin.isatty():
            return lambda: None
        # Simpan mode terminal saat ini (yang benar, sebelum command).
        saved = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        return lambda: None

    def _restore():
        try:
            if sys.stdin.isatty():
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved)
        except Exception:
            pass

    return _restore


def tool_bash(command: str, timeout: int = 60) -> str:
    # Model kadang mengirim timeout sebagai string (mis. "10") karena JSON
    # yang ditulisnya tidak selalu konsisten tipe datanya. `timeout: int`
    # di signature ini cuma type hint, TIDAK memaksa konversi -- kalau
    # dibiarkan string, subprocess.communicate(timeout=...) akan crash
    # dengan "unsupported operand type(s) for +: 'float' and 'str'" saat
    # menghitung endtime (time.monotonic() + timeout) secara internal.
    # Konversi eksplisit di sini supaya tool tetap jalan berapa pun tipe
    # yang dikirim model, dan gagal dengan pesan jelas kalau memang bukan
    # angka valid (bukan TypeError kriptik dari dalam modul subprocess).
    try:
        timeout = float(timeout) if not isinstance(timeout, (int, float)) else timeout
    except (TypeError, ValueError):
        return f"[ERROR] Argumen timeout tidak valid: {timeout!r} (harus berupa angka detik)"

    # SEBELUMNYA: timeout tidak di-clamp sama sekali, beda dengan
    # tool_security_scan yang membatasi 5-1800 detik. Model bisa mengirim
    # timeout sangat besar (atau command long-running seperti dev server)
    # dan membuat proc.communicate() memblokir sangat lama. Karena tool ini
    # dipanggil sinkron dari loop utama CLI, itu bisa membuat seluruh CLI
    # tampak "hang" -- tidak bisa menerima input/konfirmasi user sampai
    # timeout tercapai. Clamp ke rentang yang sama dengan security_scan
    # supaya ada batas atas yang pasti.
    _BASH_TIMEOUT_MIN, _BASH_TIMEOUT_MAX = 1, 1800
    if timeout <= 0:
        timeout = 60
    timeout = max(_BASH_TIMEOUT_MIN, min(timeout, _BASH_TIMEOUT_MAX))

    # subprocess.run(..., timeout=...) sebelumnya cuma mem-kill proses shell
    # (/bin/sh -c "...") saat timeout, BUKAN child process yang di-spawn
    # olehnya (mis. server yang di-background, pipeline `a | b | c`, proses
    # `npm run build` yang bikin child sendiri). Child-child itu jadi orphan
    # yang tetap hidup memakai CPU/memory/port setelah CLI melaporkan
    # timeout. Fix: jalankan command di process group baru (start_new_session)
    # supaya saat timeout kita bisa kill SELURUH group, bukan cuma leader-nya.
    proc = None
    # Jaring pengaman: simpan mode terminal sebelum command dijalankan, lalu
    # kembalikan di `finally` -- menutup kasus di mana command mengubah mode
    # terminal (mis. stty -echo/raw, program interaktif) dan tidak
    # mengembalikannya, sehingga kursor menghilang & tulisan tak terbaca
    # setelah tool selesai.
    restore_term = _restore_terminal_mode()
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=state.WORKDIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # PENTING: redirect stdin ke DEVNULL. SEBELUMNYA stdin TIDAK
            # di-redirect, jadi child process bash mewarisi stdin terminal
            # utama. Kalau command yang dijalankan mengubah mode terminal
            # (mis. `stty -echo`, `stty raw`, program interaktif seperti
            # vim/less/top/htop yang memanggil tcsetattr), atau dijalankan
            # di background (`&`) dan tetap berbagi terminal, mode terminal
            # utama bisa rusak -- gejala: kursor menghilang & tulisan yang
            # diketik tidak terbaca (echo mati / raw mode) setelah tool
            # selesai. Redirect ke DEVNULL mencegah child mengubah mode
            # terminal melalui fd stdin yang diwarisi.
            stdin=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        out, err = proc.communicate(timeout=timeout)
        out = out.strip()
        err = err.strip()
        combined = f"[exit_code={proc.returncode}]\n"
        if out:
            combined += f"STDOUT:\n{out}\n"
        if err:
            combined += f"STDERR:\n{err}\n"
        combined = combined.strip() or "(tidak ada output)"
        return _cap_output(combined)
    except subprocess.TimeoutExpired:
        if proc is not None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass  # proses sudah selesai duluan di antara timeout & kill
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass
        return (
            f"[ERROR] Command timeout setelah {timeout} detik "
            "(proses beserta seluruh child-nya sudah dihentikan)"
        )
    except Exception as e:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        return f"[ERROR] {e}"
    finally:
        # Selalu kembalikan mode terminal, apa pun hasilnya (sukses, timeout,
        # atau error). Ini jaring pengaman terakhir untuk mencegah kursor
        # menghilang / tulisan tak terbaca setelah command bash selesai.
        restore_term()
