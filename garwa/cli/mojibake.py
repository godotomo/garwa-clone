"""cli/mojibake.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
"""

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from . import _state as state



def _scan_text_for_mojibake(text: str) -> list:
    """Kembalikan list (line_no, col, run_chars) untuk tiap kemunculan
    fingerprint mojibake di `text`. Baris/kolom 1-indexed relatif ke
    `text` itu sendiri (isi satu argumen), bukan ke file.

    Sebuah run HANYA dianggap temuan valid kalau:
      - mengandung >=1 karakter C1 control (0x80-0x9F) -- ini SENDIRIAN
        sudah cukup mencurigakan, karena C1 control tidak pernah dipakai
        sengaja di source code/dokumen biasa; ATAU
      - berupa klaster >=2 karakter fingerprint berurutan -- karena
        mojibake UTF-8<->Latin-1 asli SELALU muncul sebagai pasangan/deret
        byte lead+continuation (mis. 'Ã©', 'â€™'), tidak pernah cuma satu
        karakter berdiri sendiri.
    Aturan ini sengaja MENGABAIKAN kemunculan tunggal satu karakter
    fingerprint (mis. ligatur Prancis 'œ' pada 'cœur', atau simbol '™'
    berdiri sendiri) -- itu false positive: teks natural yang legit, bukan
    hasil salah encode.
    """
    findings = []
    for line_no, line in enumerate(text.split("\n"), start=1):
        run_start = None
        run_chars = []
        for col, ch in enumerate(line, start=1):
            suspicious = (ord(ch) in state._MOJIBAKE_C1_CONTROL_RANGE
                          or ch in state._MOJIBAKE_FINGERPRINT_CHARS)
            if suspicious:
                if run_start is None:
                    run_start = col
                run_chars.append(ch)
            else:
                if run_start is not None:
                    if _is_valid_mojibake_run(run_chars):
                        findings.append((line_no, run_start, "".join(run_chars)))
                    run_start, run_chars = None, []
        if run_start is not None and _is_valid_mojibake_run(run_chars):
            findings.append((line_no, run_start, "".join(run_chars)))
    return findings


def _is_valid_mojibake_run(run_chars: list) -> bool:
    has_c1 = any(ord(ch) in state._MOJIBAKE_C1_CONTROL_RANGE for ch in run_chars)
    return has_c1 or len(run_chars) >= 2


def _iter_string_values(value, path=""):
    """Iterasi rekursif semua nilai string dalam struktur `arguments` tool
    (dict/list/str campur bisa saja terjadi -- mis. edit_file dengan
    beberapa operasi sekaligus), sambil melacak path argumen supaya pesan
    error bisa menunjuk persis argumen mana yang bermasalah.
    """
    if isinstance(value, str):
        yield path or "(argumen)", value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _iter_string_values(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from _iter_string_values(v, f"{path}[{i}]")


def scan_tool_arguments_for_mojibake(arguments: dict) -> list:
    """Scan SEMUA nilai string di `arguments` sebuah tool_call untuk
    fingerprint mojibake, SEBELUM tool tsb dieksekusi -- jadi sebelum apa
    pun sempat ditulis ke disk oleh handler write_file/edit_file/dst.
    Return list (arg_path, line_no, col, run_chars); list kosong = bersih.
    """
    report = []
    for arg_path, text in _iter_string_values(arguments):
        for line_no, col, chars in _scan_text_for_mojibake(text):
            report.append((arg_path, line_no, col, chars))
    return report


def _format_mojibake_error(tool_name: str, report: list) -> str:
    lines = [
        f"[ERROR] Argumen untuk tool '{tool_name}' mengandung kemungkinan "
        "karakter mojibake/rusak (hasil salah encode UTF-8<->Latin-1). "
        "Tool ini TIDAK dijalankan -- karakter rusak ini kalau sampai "
        "tertulis ke file akan menyulitkan proses edit berikutnya (mis. "
        "str_replace/old_str gagal menemukan teks target karena byte-nya "
        "tidak persis sama dengan yang terlihat).",
    ]
    for arg_path, line_no, col, chars in report:
        codepoints = " ".join(f"U+{ord(ch):04X}" for ch in chars)
        lines.append(
            f"  - argumen '{arg_path}', baris {line_no}, kolom {col}: "
            f"{chars!r} ({codepoints})"
        )
    lines.append(
        "Perbaiki argumen tsb lalu panggil ulang tool yang sama: gunakan "
        "karakter ASCII biasa (mis. '->' untuk panah, '--' untuk en-dash) "
        "atau escape eksplisit (mis. '\\u2192'), JANGAN karakter Unicode "
        "literal untuk simbol semacam ini."
    )
    return "\n".join(lines)
