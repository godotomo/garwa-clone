"""cli/tool_exec.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
"""
import json
import os

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from ..tools import TOOLS
from .. import tools as tools_module
from .. import tool_runtime
from . import _state as state
from .colors import C
from .colors import c
from .mojibake import _format_mojibake_error
from .mojibake import scan_tool_arguments_for_mojibake
from .text_utils import confirm



def _tool_may_prompt(name: str, arguments: dict, auto_approve: bool) -> bool:
    """Apakah pemanggilan tool ini berpotensi memunculkan prompt konfirmasi
    ke stdin (sehingga spinner harus ditiadakan)?

    Meskipun auto_approve aktif, ada dua kategori yang TETAP meminta konfirmasi
    eksplisit dan tidak dilewati:
      1. Tool tulis (write_file/edit_file) dengan path target di luar workdir
         saat sandbox aktif -> prompt [SANDBOX] di execute_tool().
      2. Tool bash yang cocok pola berbahaya (destructive "force") -> prompt
         konfirmasi destructive di execute_tool().

    Dipanggil oleh agent_loop.py untuk memutuskan apakah aman menyalakan
    Spinner. Kalau fungsi ini mengembalikan True, spinner ditiadakan agar
    prompt konfirmasi tidak tertutup karakter spinner.
    """
    if not auto_approve:
        # Tanpa auto-approve, tool destruktif apa pun bisa memunculkan prompt.
        return True

    # 1) Tool tulis ke path eksternal (sandbox aktif).
    if name in ("write_file", "edit_file") and isinstance(arguments, dict):
        target = arguments.get("path")
        if isinstance(target, str) and target:
            candidate = target if os.path.isabs(target) else os.path.join(
                tools_module.state.WORKDIR, target)
            real_candidate = os.path.realpath(candidate)
            real_workdir = os.path.realpath(tools_module.state.WORKDIR)
            try:
                _outside = os.path.commonpath([real_candidate, real_workdir]) != real_workdir
            except ValueError:
                _outside = True
            if _outside and tools_module.state.SANDBOX_ENABLED:
                return True

    # 2) Tool bash berbahaya (destructive "force").
    if name == "bash":
        spec = TOOLS.get("bash")
        destructive = spec["destructive"] if spec else False
        if callable(destructive):
            destructive = destructive(arguments)
        if destructive == "force":
            return True

    return False


def execute_tool(name: str, arguments: dict, auto_approve: bool) -> str:

    resolved_name = tool_runtime.REGISTRY.resolve(name)
    if resolved_name not in TOOLS:
        return f"[ERROR] Tool '{name}' tidak dikenal. Tool yang tersedia: {', '.join(TOOLS.keys())}"

    name = resolved_name
    spec = TOOLS[name]

    # Hitung tool call yang benar-benar dieksekusi (bukan yang gagal parse)
    # untuk ditampilkan di status bar (tools:N).
    state.TOOL_CALL_TOTAL += 1

    if isinstance(arguments, dict) and "_raw" in arguments:
        print(c(f"  → memanggil tool: {name}({json.dumps(arguments, ensure_ascii=False)})", C.CYAN))
        raw_preview = arguments.get("_raw")
        raw_preview = "" if raw_preview is None else str(raw_preview)
        if len(raw_preview) > 400:
            raw_preview = raw_preview[:400] + "...(dipotong)"
        error_msg = (
            f"[ERROR] Argumen untuk tool '{name}' bukan JSON yang valid. "
            "Ini BUKAN cuma salah format (key tanpa kutip, escape salah, "
            "dst -- semua sudah dicoba diperbaiki otomatis dan tetap "
            "gagal); kemungkinan besar generation Anda TERPOTONG di "
            "tengah menulis argumen (mis. kehabisan batas token output "
            "sebelum selesai menulis sebuah string panjang). Argumen "
            f"mentah yang diterima: {raw_preview!r}\n"
            "Kirim ulang PANGGILAN TOOL INI dari awal dengan argumen JSON "
            "yang LENGKAP dan valid. Kalau argumen yang panjang (mis. "
            "'new_str'/'content') adalah penyebabnya, pertimbangkan "
            "memecahnya jadi beberapa panggilan edit yang lebih kecil "
            "supaya tidak terpotong lagi."
        )
        print(c(f"  {error_msg}", C.RED))
        return error_msg

    mojibake_report = scan_tool_arguments_for_mojibake(arguments)
    if mojibake_report:
        error_msg = _format_mojibake_error(name, mojibake_report)
        print(c(f"  {error_msg}", C.RED))
        return error_msg

    print(c(f"  → memanggil tool: {name}({json.dumps(arguments, ensure_ascii=False)})", C.CYAN))

    destructive = spec["destructive"]
    if callable(destructive):
        destructive = destructive(arguments)

    # ------------------------------------------------------------------
    # Path eksternal (di luar workdir) untuk tool tulis/hapus.
    #
    # SEBELUMNYA: _resolve() di sandbox selalu menolak path luar workdir,
    # jadi meskipun user sudah menjawab 'y' di prompt konfirmasi di bawah,
    # write_file/edit_file ke /tmp/... tetap gagal dengan error sandbox.
    # Persetujuan user tidak pernah diteruskan ke lapisan sandbox.
    #
    # Fix: untuk tool tulis yang punya argumen 'path', cek apakah path
    # targetnya di luar workdir. Kalau iya, minta konfirmasi EKSPLISIT
    # (terpisah dari konfirmasi destructive umum). Kalau user setuju,
    # daftarkan path ke ALLOWED_EXTERNAL_PATHS supaya _resolve_writable()
    # di lapisan sandbox mengizinkannya. Kalau ditolak, batalkan.
    # ------------------------------------------------------------------
    if name in ("write_file", "edit_file") and isinstance(arguments, dict):
        target = arguments.get("path")
        if isinstance(target, str) and target:
            candidate = target if os.path.isabs(target) else os.path.join(
                tools_module.state.WORKDIR, target)
            real_candidate = os.path.realpath(candidate)
            real_workdir = os.path.realpath(tools_module.state.WORKDIR)
            try:
                _outside = os.path.commonpath([real_candidate, real_workdir]) != real_workdir
            except ValueError:
                _outside = True  # beda drive (Windows) -> di luar workdir
            if _outside and tools_module.state.SANDBOX_ENABLED:
                print(c(
                    f"  [SANDBOX] Path target berada DI LUAR working directory:\n"
                    f"            {real_candidate}\n"
                    f"            (workdir: {real_workdir})",
                    C.YELLOW,
                ))
                if not confirm(
                    f"Izinkan {name} menulis ke path di luar working directory di atas?"
                ):
                    return (
                        f"[DITOLAK] User menolak penulisan ke path di luar working directory: "
                        f"{real_candidate}. Tool '{name}' dibatalkan."
                    )
                # Setujui path spesifik ini DAN parent dir-nya (supaya
                # operasi lanjutan seperti edit ulang/hapus di folder yang
                # sama tidak perlu konfirmasi berulang).
                tools_module.state.ALLOWED_EXTERNAL_PATHS.add(real_candidate)
                parent = os.path.dirname(real_candidate)
                if parent:
                    tools_module.state.ALLOWED_EXTERNAL_PATHS.add(parent)

    needs_confirm = destructive == "force" or (destructive and not auto_approve)
    if needs_confirm:
        if not confirm(f"Izinkan eksekusi tool '{name}' di atas?"):
            return "[DITOLAK] User menolak eksekusi tool ini."

    return tool_runtime.run_tool_with_runtime(
        name=name,
        arguments=arguments,
        handler=spec["handler"],
        index=state._tool_call_index.get(),
        hooks=tool_runtime.DEFAULT_HOOKS,
    )
