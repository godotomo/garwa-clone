"""cli/json_repair.py
Dipecah otomatis dari cli.py (lihat cli/_state.py untuk state bersama).
"""
import json
import re

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from . import _state as state



def _repair_unquoted_json_keys(raw_json: str) -> str:
    """Perbaiki key JSON yang TIDAK dikutip (mis. `{name: "bash", arguments:
    {...}}`) menjadi key yang dikutip (`{"name": "bash", "arguments": {...}}`).

    Kejadian nyata yang mendasari ini: model kecil (mis. Garwa 4B/12B) kadang
    menulis tool_call dengan key tanpa tanda kutip ganda, yang membuat
    json.loads() gagal dengan pesan "Expecting property name enclosed in
    double quotes" (JSONDecodeError di posisi key pertama). Ini beda dari
    kasus backslash escape yang sudah ditangani _repair_invalid_json_escapes()
    -- di sini masalahnya key-nya sendiri tidak dikutip.

    Pendekatan: regex yang mengutip key yang valid (identifier: huruf/angka/
    underscore, tidak diawali digit) yang muncul tepat setelah `{` atau `,`
    dan diikuti `:`. Hanya key yang BELUM dikutip yang diubah (yang sudah
    dikutip `"key":` tidak cocok pola karena regex menuntut identifier
    langsung setelah `{`/`,` tanpa tanda kutip).

    KETERBATASAN yang disengaja (jujur soal batasnya):
      - Regex ini TIDAK bisa membedakan `{`/`,` di dalam string value vs di
        luar struktur. Kalau sebuah string value kebetulan mengandung pola
        `, key:` (mis. teks bebas di dalam argumen), regex bisa salah
        mengutip. Untuk mengurangi risiko ini, fungsi ini HANYA dipanggil
        sebagai fallback SETELAH json.loads() gagal dengan pesan spesifik
        "Expecting property name enclosed in double quotes" (lihat
        extract_tool_call) -- jadi tidak pernah menyentuh JSON yang sudah
        valid. Risiko sisa tetap ada, tapi jauh lebih kecil daripada
        membiarkan seluruh giliran gagal.
      - Key yang mengandung karakter non-identifier (spasi, tanda hubung,
        dst.) TIDAK diperbaiki di sini -- itu di luar cakupan pola umum
        model kecil yang biasanya memakai key sederhana (name/arguments/
        path/command/dst).
    """
    return re.sub(
        r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)',
        r'\1"\2"\3',
        raw_json,
    )


def _repair_unquoted_json_values(raw_json: str) -> str:
    """Perbaiki VALUE string JSON yang TIDAK dikutip (mis. `{"name": bash,
    "arguments": {"command": ls}}`) menjadi value yang dikutip
    (`{"name": "bash", "arguments": {"command": "ls"}}`).

    Kejadian nyata yang mendasari ini: model kecil (mis. Garwa 4B/12B) kadang
    menulis tool_call dengan key DAN value sama-sama tanpa tanda kutip ganda
    (gaya `{name: bash, arguments: {command: ls}}`). _repair_unquoted_json_keys()
    hanya mengutip KEY, sehingga hasilnya `{"name": bash, ...}` -- json.loads()
    masih gagal dengan "Expecting property name enclosed in double quotes"
    (di posisi value pertama). Fungsi ini menutup celah itu dengan mengutip
    value identifier yang tidak dikutip.

    Pendekatan: regex yang mengutip identifier (huruf/angka/underscore, plus
    titik, garis miring, dan tanda hubung untuk path/command) yang muncul
    tepat setelah `:` dan diikuti `,` atau `}`. Value yang SUDAH dikutip
    (`"bash"`) tidak cocok karena regex menuntut identifier langsung setelah
    `:` tanpa tanda kutip. Literal JSON `true`/`false`/`null` dan angka
    sengaja TIDAK dikutip (harus tetap jadi boolean/null/number agar
    json.loads() menerimanya).

    KETERBATASAN yang disengaja (jujur soal batasnya):
      - Regex ini TIDAK bisa membedakan `:` di dalam string value vs di luar
        struktur. Kalau sebuah string value kebetulan mengandung pola
        `: word,` (mis. teks bebas di dalam argumen), regex bisa salah
        mengutip. Untuk mengurangi risiko ini, fungsi ini HANYA dipanggil
        sebagai fallback SETELAH json.loads() gagal (lihat extract_tool_call),
        jadi tidak pernah menyentuh JSON yang sudah valid.
      - Value yang mengandung spasi (mis. `command: ls -la`) TIDAK diperbaiki
        di sini -- itu di luar cakupan pola umum model kecil yang biasanya
        memakai value sederhana (bash/ls/pwd/dst).
    """
    # Implementasi tokenizer state-machine (bukan regex): regex naif tidak bisa
    # membedakan kolon STRUKTURAL (`"key": value`) dari kolon DI DALAM string
    # value yang sudah dikutip (mis. path `"C:/Users/a"`), sehingga bisa salah
    # mengutip value yang SUDAH dikutip dan menghasilkan JSON rusak yang tidak
    # bisa diperbaiki fungsi lain. Tokenizer di bawah hanya mengutip bareword
    # yang muncul di LEVEL TOP (di luar string), jadi value yang sudah dikutip
    # dan literal true/false/null/angka tidak pernah disentuh.
    out = []
    i = 0
    n = len(raw_json)
    in_string = False
    while i < n:
        ch = raw_json[i]
        if ch == '"':
            # toggle status string (abaikan escape \\")
            if in_string and i > 0 and raw_json[i - 1] == "\\":
                pass  # escaped quote, tetap di dalam string
            else:
                in_string = not in_string
            out.append(ch)
            i += 1
            continue
        if in_string:
            out.append(ch)
            i += 1
            continue
        # Di level top: cari kolon yang diikuti bareword value.
        if ch == ":":
            j = i + 1
            while j < n and raw_json[j] in " \t\r\n":
                j += 1
            # Value harus bareword: bukan kutip, bukan kurung kurawal, bukan
            # spasi, bukan koma/penutup. Kalau bukan bareword, biarkan apa adanya.
            if j < n and raw_json[j] not in '"{}[],: \t\r\n':
                k = j
                while k < n and raw_json[k] not in ',{} \t\r\n':
                    k += 1
                val = raw_json[j:k]
                if val not in ("true", "false", "null") and not re.fullmatch(r"-?\d+(\.\d+)?", val):
                    out.append(":")
                    out.append(raw_json[i + 1:j])  # spasi setelah kolon
                    out.append('"')
                    out.append(val)
                    out.append('"')
                    i = k
                    continue
        out.append(ch)
        i += 1
    return "".join(out)


def _repair_single_quoted_json(raw_json: str) -> str:
    """Perbaiki JSON yang memakai tanda kutip TUNGGAL untuk key dan/atau
    value string (mis. `{'name': 'bash', 'arguments': {'command': 'ls'}}`)
    menjadi tanda kutip ganda standar JSON.

    Kejadian nyata yang mendasari ini: sebagian model (terutama yang kecil
    atau yang dilatih dengan contoh Python dict) kadang menulis tool_call
    memakai sintaks dict Python -- tanda kutip tunggal untuk key dan value.
    json.loads() lalu gagal dengan pesan "Expecting property name enclosed
    in double quotes" di posisi key pertama (char 1 setelah `{`), yang TIDAK
    ditangani _repair_unquoted_json_keys() (regex-nya menuntut identifier
    langsung setelah `{`/`,` tanpa tanda kutip apa pun).

    Pendekatan: ganti SEMUA tanda kutip tunggal menjadi tanda kutip ganda.
    Ini aman untuk kasus tool-call karena:
      - JSON valid tidak pernah memakai tanda kutip tunggal, jadi fungsi ini
        hanya dipanggil sebagai fallback SETELAH json.loads() gagal (lihat
        extract_tool_call), tidak pernah menyentuh JSON yang sudah valid.
      - Di dalam JSON yang memakai tanda kutip tunggal, tanda kutip tunggal
        hanya muncul sebagai delimiter string (Python dict tidak punya
        escape `\'` yang umum dipakai di dalam string yang dikutip tunggal
        -- kalau ada, itu kasus langka dan akan tetap gagal, jatuh ke
        PARSE_ERROR seperti sebelumnya).
    """
    return raw_json.replace("'", '"')


def _repair_invalid_json_escapes(raw_json: str) -> str:
    """Perbaiki backslash tunggal yang json.loads() secara eksplisit
    tandai sebagai escape tidak valid, satu per satu berdasarkan posisi
    PERSIS dari JSONDecodeError -- bukan menebak lewat pola/regex (lihat
    komentar panjang di atas, termasuk keterbatasannya, untuk alasannya).
    Return teks apa adanya (tidak berubah) kalau errornya bukan soal
    escape, atau kalau posisi error ternyata tidak menunjuk ke backslash
    (defensif terhadap perubahan pesan error antar versi Python).
    """
    text = raw_json
    for _ in range(state._MAX_JSON_ESCAPE_REPAIR_ATTEMPTS):
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError as e:
            if "Invalid \\escape" not in e.msg:
                return text
            pos = e.pos
            if pos < 0 or pos >= len(text) or text[pos] != "\\":
                return text
            text = text[:pos] + "\\" + text[pos:]
    return text


def _find_json_object_end(text: str, start: int) -> int:
    """Kembalikan indeks tepat SETELAH penutup `}` dari JSON object berimbang
    yang dimulai di `start` (posisi karakter `{`), menghormati string
    (double/single-quoted) dan backslash escape. Mengembalikan -1 bila tidak
    ditemukan `{` pembuka atau object tidak berimbang.

    Berbeda dari `json.JSONDecoder().raw_decode` yang menuntut JSON STANDAR,
    matcher ini HANYA menghitung kedalaman kurung kurawal di luar string —
    jadi tetap bisa menemukan batas blok untuk JSON yang TIDAK valid standar
    (key tanpa kutip, tanda kutip tunggal, placeholder `...`, dll.) yang
    nantinya akan diperbaiki `_parse_raw_json`. Pada saat yang sama ia tetap
    menghormati `}` di dalam string dan object bersarang.
    """
    n = len(text)
    i = start
    while i < n and text[i] in " \t\r\n":
        i += 1
    if i >= n or text[i] != "{":
        return -1
    depth = 0
    quote = None
    while i < n:
        ch = text[i]
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch == '"' or ch == "'":
            quote = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


_FENCE_MARKER_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")


def _fenced_code_spans(text: str):
    """Span `(start, end)` isi blok kode markdown yang BENAR-BENAR TERTUTUP.

    Dipakai untuk membedakan `<tool_call>` SUNGGUHAN dari `<tool_call>` yang
    cuma CONTOH/dokumentasi di dalam ``` ... ``` (mis. model menjelaskan
    format tool call, atau mengutip instruksi system prompt). Tanpa ini,
    contoh di dalam fence ikut dieksekusi sebagai pemanggilan tool nyata.

    Heuristik sengaja KONSERVATIF: hanya pasangan fence yang punya baris
    penutup yang dihitung. Fence yang dibuka tapi tidak pernah ditutup
    (model lupa menutup) TIDAK menghasilkan span apa pun, sehingga
    `<tool_call>` di dalamnya tetap dianggap nyata -- ini penting supaya
    fence "menggantung" tidak menelan pemanggilan yang sah.

    Indeks `start` = tepat setelah baris pembuka (yaitu awal baris pertama
    isi fence), `end` = awal baris penutup. Baris fence itu sendiri (yang
    memuat ``` / ~~~) tidak termasuk span.
    """
    spans = []
    stack = None  # (marker_char, posisi_akhir_baris_pembuka)
    pos = 0
    for line in text.split("\n"):
        match = _FENCE_MARKER_RE.match(line)
        line_end = pos + len(line)
        if match:
            marker = match.group(1)[0]
            if stack is None:
                stack = (marker, line_end)
            elif stack[0] == marker:
                spans.append((stack[1], pos))
                stack = None
        pos = line_end + 1
    return spans


def _iter_tool_call_blocks(text: str):
    """Yield `(start, end, raw_json)` untuk SETIAP blok `<tool_call>...</tool_call>`.

    Berbeda dari `state.TOOL_CALL_RE` (non-greedy ``{.*?}``), iterator ini
    memakai brace-matcher berimbang (lihat `_find_json_object_end`): mulai
    tepat setelah tag pembuka `<tool_call>`, lalu cari JSON object lengkap
    dengan menghormati tanda kutip/escape di dalam string dan object bersarang.
    Ini menutup tiga celah regex non-greedy:

      - JSON yang memuat `}` di dalam string value TIDAK lagi terpotong.
      - Fragmen prosa/kutipan yang kebetulan memuat `{...}` TIDAK disalahartikan
        sebagai tool_call (matcher hanya aktif SETELAH tag pembuka).
      - Tidak ada kebocoran blok mentah ke visible_text karena blok hanya
        diakui bila diawali tag pembuka `<tool_call>` diikuti object berimbang.

    `start` = posisi karakter `"<"` dari tag pembuka; `end` = posisi tepat
    setelah tag penutup `</tool_call>` (bila ada) atau setelah akhir object
    JSON (bila tag penutup tidak ada). Yield semua blok ber-object berimbang;
    validitas isinya diserahkan ke `_parse_raw_json`.
    """
    fenced = _fenced_code_spans(text)

    def _in_fence(position: int) -> bool:
        for span_start, span_end in fenced:
            if span_start <= position < span_end:
                return True
        return False

    idx = 0
    n = len(text)
    while True:
        open_pos = text.find(state.TOOL_OPEN, idx)
        if open_pos == -1:
            return
        if _in_fence(open_pos):
            # P2 (code fence): marker ini berada di dalam ``` ... ``` tertutup
            # -> itu CONTOH/dokumentasi, bukan pemanggilan nyata. Lewati.
            idx = open_pos + len(state.TOOL_OPEN)
            continue
        # Mulai scan JSON tepat setelah tag pembuka; lewati whitespace.
        json_start = open_pos + len(state.TOOL_OPEN)
        while json_start < n and text[json_start] in " \t\r\n":
            json_start += 1
        if json_start >= n:
            return
        end = _find_json_object_end(text, json_start)
        if end == -1:
            # Tidak ada object berimbang setelah tag ini; maju melewati tag
            # pembuka supaya blok berikutnya masih bisa ditemukan.
            idx = json_start
            continue
        raw_json = text[json_start:end]
        close_pos = text.find(state.TOOL_CLOSE, end)
        block_end = close_pos + len(state.TOOL_CLOSE) if close_pos != -1 else end
        yield open_pos, block_end, raw_json
        idx = block_end


def _iter_tool_call_json_blocks(text: str):
    """Yield isi JSON (string) dari SETIAP blok `<tool_call>...</tool_call>`."""
    for _open, _end, raw_json in _iter_tool_call_blocks(text):
        yield raw_json


def strip_tool_call_blocks(text: str) -> str:
    """Hapus SEMUA blok `<tool_call>...</tool_call>` valid dari `text`.

    Memakai matcher yang SAMA dengan `extract_tool_calls` (brace-matcher
    berimbang), sehingga blok yang dihapus dari visible_text persis blok yang
    dieksekusi — tidak lebih, tidak kurang. Blok yang JSON-nya tidak valid
    TIDAK dihapus (biar tetap terlihat user sebagai bukti error, bukan
    lenyap senyap).
    """
    spans = list(_iter_tool_call_blocks(text))
    if not spans:
        return text
    out = text
    for start, end, _raw in reversed(spans):
        out = out[:start] + out[end:]
    return out


def extract_tool_calls(text: str):
    """Ekstrak SEMUA tool_call valid dari `text` sebagai list `(name, arguments)`.

    Setiap elemen memakai logika parse yang SAMA dengan `extract_tool_call`
    (perbaikan escape/key/value/kutip tunggal + deteksi PARSE_ERROR), tapi
    mencakup seluruh blok berurutan, bukan hanya yang pertama. Ini dasar untuk
    memperbaiki bug P0: blok ke-2..n yang selama ini dibuang.

    Elemen yang berupa placeholder `{...}` di-skip (konsisten dengan perilaku
    `extract_tool_call` yang mengembalikan (None, None) untuk kasus itu);
    blok yang gagal di-parse direpresentasikan sebagai ("PARSE_ERROR", msg).
    """
    results = []
    for raw_json in _iter_tool_call_json_blocks(text):
        name, arguments = _parse_raw_json(raw_json)
        if name is None and arguments is None:
            # placeholder {...} -> skip, bukan berhenti (bug lama)
            continue
        results.append((name, arguments))
    return results


def _parse_raw_json(raw_json: str):
    """Parse satu blob JSON tool_call menjadi (name, arguments).

    Logika yang sama persis dengan badan `extract_tool_call` (setelah
    regex match), dipisah supaya `extract_tool_call` dan `extract_tool_calls`
    tidak menduplikasi kode perbaikan JSON.
    """
    if re.fullmatch(r"\s*\{\s*\.\.\.\s*\}\s*", raw_json):
        return None, None
    # Kutipan TEMPLATE/contoh dari system prompt BUKAN tool_call nyata.
    #
    # skills/system_prompt.py menampilkan contoh literal berisi nama placeholder
    # bersudut (nama tool ditulis sebagai tag) plus isi field yang diganti
    # tanda titik-titik. Model acap MENGUTIP contoh ini di prosa (saat
    # menjelaskan aturan format, atau menyalin template sebelum tool_call
    # aslinya). Tanpa guard ini, kutipan tsb ikut ter-parse, gagal
    # (placeholder), lalu jadi PARSE_ERROR -> mengotori _error_history ->
    # memicu intervensi ERROR-LOOP palsu dan pesan [LOOP]/[STOP] yang
    # membingungkan, padahal tool_call asli di blok berikutnya VALID.
    #
    # Sinyal (sengaja konservatif, butuh KEDUANYA):
    #   (a) ada nama bertanda sudut, mis. tag nama tool;
    #   (b) ada tanda titik-titik sebagai placeholder isi field.
    # Tool_call nyata tidak memakai nama bertanda sudut, jadi risiko menelan
    # pemanggilan sungguhan sangat kecil. Kasus uji yang mengharapkan
    # PARSE_ERROR (name="bash" dengan arguments placeholder) TIDAK terpengaruh
    # karena tidak memuat nama bertanda sudut.
    _ELLIPSIS = "." * 3
    if _ELLIPSIS in raw_json and re.search(r'"<\s*[^">]*\s*>"', raw_json):
        return None, None
    try:
        obj = json.loads(raw_json)
    except json.JSONDecodeError as e:

        candidates = [raw_json]
        repaired_esc = _repair_invalid_json_escapes(raw_json)
        repaired_uq = _repair_unquoted_json_keys(raw_json)
        repaired_sq = _repair_single_quoted_json(raw_json)
        repaired_uv = _repair_unquoted_json_values(raw_json)
        for cand in (repaired_esc, repaired_uq, repaired_sq, repaired_uv):
            if cand not in candidates:
                candidates.append(cand)

        combined1 = _repair_unquoted_json_keys(repaired_esc)
        combined2 = _repair_invalid_json_escapes(repaired_uq)
        for cand in (combined1, combined2):
            if cand not in candidates:
                candidates.append(cand)

        combined3 = _repair_single_quoted_json(repaired_uq)
        combined4 = _repair_unquoted_json_keys(repaired_sq)
        combined5 = _repair_single_quoted_json(repaired_esc)
        combined6 = _repair_invalid_json_escapes(repaired_sq)
        for cand in (combined3, combined4, combined5, combined6):
            if cand not in candidates:
                candidates.append(cand)

        combined7 = _repair_unquoted_json_values(repaired_uq)
        combined8 = _repair_unquoted_json_keys(repaired_uv)
        combined9 = _repair_unquoted_json_values(repaired_esc)
        combined10 = _repair_unquoted_json_values(repaired_sq)
        combined11 = _repair_single_quoted_json(repaired_uv)
        for cand in (combined7, combined8, combined9, combined10, combined11):
            if cand not in candidates:
                candidates.append(cand)

        obj = None
        for cand in candidates:
            try:
                obj = json.loads(cand)
                break
            except json.JSONDecodeError:
                continue
        if obj is None:
            # Klasifikasikan kegagalan berdasarkan pesan JSONDecodeError (e.msg)
            # alih-alih menebak lewat substring di raw_json. Khususnya
            # 'Unterminated string' menandakan string value tidak ditutup tanda
            # kutip; sebelumnya dicek lewat '"..." in raw_json' yang memberi
            # diagnosa keliru (placeholder) pada error string tak tertutup.
            if e.msg and "Unterminated string" in e.msg:
                return "PARSE_ERROR", (
                    "tool_call mengandung string yang TIDAK ditutup tanda kutip "
                    "(ada value string yang kurang penutup '\"'). Tutup semua "
                    f"string dengan benar. detail={e} | raw_json={raw_json!r}"
                )
            if re.search(r'"[^"]*\.\.\.[^"]*"|\{\s*\.\.\.\s*\}', raw_json):
                return "PARSE_ERROR", (
                    f"tool_call mengandung placeholder '...' (ellipsis): model "
                    f"menulis '...' sebagai pengganti isi field sehingga JSON "
                    f"tidak bisa diperbaiki otomatis. Tulis field lengkap "
                    f"(mis. \"arguments\": {{...}}), bukan '...'. "
                    f"raw_json={raw_json!r}"
                )
            return "PARSE_ERROR", f"{e} | raw_json={raw_json!r}"

    name = obj.get("name")
    arguments = obj.get("arguments", {})

    if isinstance(name, str) and name.lstrip().startswith("{"):
        try:
            inner = json.loads(name)
        except json.JSONDecodeError:
            inner = None
        if isinstance(inner, dict) and "name" in inner:
            name = inner.get("name")
            inner_arguments = inner.get("arguments", arguments)
            if isinstance(inner_arguments, dict):
                arguments = inner_arguments

    if not isinstance(arguments, dict):
        return "PARSE_ERROR", "arguments harus berupa objek JSON"
    return name, arguments


def extract_tool_call(text: str):
    """Ekstrak tool_call PERTAMA dari `text` (kontrak lama, tetap (name, arguments)).

    Untuk kompatibilitas dengan pemanggil yang mem-monkeypatch fungsi ini dengan
    `fake_extract(text) -> (name, args)` (tests/test_cli_utils.py), fungsi tetap
    ber-signature `(text) -> (name, arguments)`. Implementasi kini didelegasikan
    ke `extract_tool_calls` agar logika parse tidak terduplikasi.

    Mengembalikan (None, None) bila tidak ada tool_call valid; placeholder
    `{...}` juga dianggap (None, None) demi kompatibilitas perilaku lama.
    """
    calls = extract_tool_calls(text)
    if not calls:
        return None, None
    return calls[0]
