"""cli/tool_schema/alt_syntax.py
Dipecah lebih lanjut dari cli/tool_schema.py.

Selain format alternatif internal, modul ini menormalkan sintaks tool_call
"asing" milik keluarga model lain (DSML, XML invoke, function=, tag varian
spasi) menjadi blok resmi state.TOOL_OPEN/state.TOOL_CLOSE ber-JSON, SEBELUM
extract_tool_calls maupun strip_tool_call_blocks dijalankan.

Latar belakang (bukti dari DB nyata, ribuan pesan assistant): model kadang
membalas dengan format tool_call model lain, sementara extract_tool_calls
hanya mengenali blok resmi ber-JSON berimbang. Akibatnya:
  - parser live (stream_parse) menyembunyikan sisa jawaban karena melihat
    tag pembuka tool_call (state in_tool=True), TAPI
  - tidak ada satu pun tool_call yang dieksekusi.
Itulah bug "giliran terhenti": jawaban hilang dari layar, tidak ada tool yang
jalan, giliran berhenti tanpa aksi (pesan STOP di agent_loop).

Keluarga sintaks yang terverifikasi ada di data nyata:
  A. DSML: tag pembungkus tool_call + tag invoke/parameter bertanda DSML.
     Pemisah tag adalah U+FF5C (fullwidth solidus) yang tampak seperti pipe,
     ada juga varian GANDA (dua pemisah) dan varian berspasi.
  B. XML invoke: tag invoke name=... berisi tag parameter name=..., boleh
     banyak invoke berurutan, kadang ditutup tag plural lalu penutup resmi,
     ada juga varian tanpa pembungkus.
  C. function=: tag function=bash berisi tag parameter=command, sering tanpa
     penutup dan nilainya bercampur sisa JSON yang terpotong.
  D. Tag varian spasi: nama tag memakai spasi (0x20) atau underscore, dan
     penutupnya kadang berbentuk plural (calls).

Catatan keamanan: contoh sintaks di dalam fence markdown yang tertutup tetap
TIDAK dieksekusi, karena json_repair._fenced_code_spans menolak blok di dalam
fence tertutup -- konversi di sini mengubah ISI fence, bukan statusnya.
"""
import json
import re

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from .. import _state as state



def _parse_alt_tool_call_args(raw_args: str) -> dict:
    """Parse isi {...} format tool_call alternatif (key:<|"|>value<|"|>,
    dipisah koma) jadi dict argumen Python biasa. Bukan JSON, jadi tidak
    memakai json.loads() -- tiap value pada format ini selalu string.
    """
    arguments = {}
    for key, value in state._ALT_TOOL_ARG_RE.findall(raw_args):
        arguments[key] = value
    return arguments


# ---------------------------------------------------------------------------
# Normalisasi sintaks tool_call "asing" (DSML / XML invoke / function= / tag
# varian spasi). Semua varian diubah menjadi blok resmi ber-JSON supaya
# matcher di json_repair (yang brace-matcher berimbang) bisa menemukannya.
# Konvensi penting: blok yang DIEKSEKUSI = blok yang DISEMBUNYIKAN, karena
# konversi terjadi di hulu (agent_loop memanggil ini sebelum ekstraksi teks
# maupun penyembunyian blok dari visible_text).
# ---------------------------------------------------------------------------

# Pemisah tag DSML (U+FF5C dan pipe ASCII), varian tunggal maupun ganda,
# dengan spasi opsional di sekitarnya.
_DSML_MARK_RE = re.compile(r"[\uff5c|]{1,2}\s*DSML\s*[\uff5c|]{1,2}\s*")

# Tag pembuka/penutup blok tool_call dalam segala varian nama & spasi:
# tool_call / tool call / tool_calls / call / calls / function_calls.
_CALL_TAG_VARIANT_RE = re.compile(
    r"<\s*(/?)\s*(?:tool[\s_]*calls?|function[\s_]*calls?|calls?)\s*>",
    re.IGNORECASE,
)
# Varian berpipa: pipe tunggal di kiri dan/atau kanan nama tag.
_CALL_TAG_PIPE_RE = re.compile(
    r"<\s*(/?)\s*\|?\s*tool[\s_]*calls?\s*\|?\s*>",
    re.IGNORECASE,
)

_INVOKE_OPEN_RE = re.compile(r"<invoke\b([^>]*)>", re.IGNORECASE)
_INVOKE_CLOSE_RE = re.compile(r"</\s*invoke\s*>", re.IGNORECASE)
_FUNCTION_OPEN_RE = re.compile(
    r"<function(?:\s*=\s*|\s+name\s*=\s*)\s*['\"]?([A-Za-z_][\w.\-]*)['\"]?\s*>",
    re.IGNORECASE,
)
_FUNCTION_CLOSE_RE = re.compile(r"</\s*function\s*>", re.IGNORECASE)
_PARAM_OPEN_RE = re.compile(r"<parameter\b([^>]*?)>", re.IGNORECASE)
_PARAM_CLOSE_RE = re.compile(r"</\s*parameter\s*>", re.IGNORECASE)
_ATTR_NAME_RE = re.compile(
    r"name\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.IGNORECASE
)
_PARAM_EQ_NAME_RE = re.compile(r"\s*=\s*['\"]?([A-Za-z_][\w.\-]*)['\"]?\s*$")
# Sisa JSON terpotong yang menempel di ekor nilai parameter bentuk function=,
# mis. ... tail -20", "timeout": 180}} -- hanya ekor yang dipangkas.
_JSON_TAIL_JUNK_RE = re.compile(r'\s*",\s*"[A-Za-z_]\w*"\s*:\s*[^"{}]*\}\}?\s*$')


def _attr_name(attr_text: str):
    """Ambil nilai atribut name=... dari daftar atribut tag (boleh None)."""
    match = _ATTR_NAME_RE.search(attr_text or "")
    if not match:
        return None
    value = match.group(1) or match.group(2) or match.group(3) or ""
    value = value.strip()
    return value or None


def _param_name(attr_text: str):
    """Nama parameter untuk bentuk name="path" MAUPUN bentuk =path."""
    name = _attr_name(attr_text)
    if name:
        return name
    match = _PARAM_EQ_NAME_RE.match(attr_text or "")
    return match.group(1) if match else None


def _clean_param_value(value: str) -> str:
    """Buang newline pembuka / whitespace-penutup yang murni artefak format tag.

    Sengaja TIDAK memakai .strip() penuh: nilai parameter bisa berupa isi file
    (content / new_str) yang spasi serta indentasi awalnya bermakna.
    """
    if value.startswith("\r\n"):
        value = value[2:]
    elif value.startswith("\n"):
        value = value[1:]
    return re.sub(r"\n[ \t\r]*$", "", value)


def _parse_tag_params(body: str, value_terminators=()):
    """Parse isi blok invoke/function menjadi dict argumen.

    Mengembalikan None bila tidak ada satu pun tag parameter yang bisa
    dikenali -- sinyal bahwa blok ini bukan pemanggilan tool nyata (mis. cuma
    prosa yang kebetulan menyebut tag) sehingga TIDAK boleh dikonversi.
    """
    arguments = {}
    pos = 0
    while True:
        match = _PARAM_OPEN_RE.search(body, pos)
        if not match:
            break
        name = _param_name(match.group(1))
        start = match.end()
        # Akhir nilai = yang TERDEKAT di antara: penutup parameter, parameter
        # berikutnya, terminator blok, atau akhir body. Penanganan seperti ini
        # yang membuat parameter TANPA penutup (data nyata) tetap terbaca.
        end = len(body)
        closer = _PARAM_CLOSE_RE.search(body, start)
        nxt = _PARAM_OPEN_RE.search(body, start)
        if closer:
            end = min(end, closer.start())
        if nxt:
            end = min(end, nxt.start())
        for terminator in value_terminators:
            found = body.find(terminator, start)
            if found != -1:
                end = min(end, found)
        if end < start:
            end = start
        if name:
            arguments[name] = _clean_param_value(body[start:end])
        pos = end if end > start else start
    return arguments or None


def _canonical_tool_name(raw_name: str) -> str:
    """Petakan nama tool varian asing ke nama kanonik (alias + namespace titik)."""
    name = (raw_name or "").strip()
    if not name:
        return name
    lowered = name.lower()
    if "." in lowered:
        prefix, _, rest = lowered.partition(".")
        mapped = state._NAMESPACE_MAP.get(prefix, {}).get(rest)
        if mapped:
            return mapped
        lowered = rest or lowered
    return state.ALT_TOOL_NAME_ALIASES.get(lowered, lowered)


def _mk_tool_call_block(name: str, arguments: dict) -> str:
    """Bangun blok tool_call resmi ber-JSON dari nama + dict argumen."""
    payload = json.dumps(
        {"name": _canonical_tool_name(name), "arguments": arguments},
        ensure_ascii=False,
    )
    return state.TOOL_OPEN + "\n" + payload + "\n" + state.TOOL_CLOSE


def _strip_dsml_marks(text: str) -> str:
    """Buang penanda DSML (pemisah + kata DSML) dari seluruh teks."""
    if "\uff5c" not in text and "DSML" not in text:
        return text
    return _DSML_MARK_RE.sub("", text)


def _normalize_call_tag_variants(text: str) -> str:
    """Normalkan tag tool_call varian nama/spasi/pipa ke bentuk kanonik."""
    if "call" not in text.lower():
        return text

    def _replace(match: "re.Match") -> str:
        return state.TOOL_CLOSE if match.group(1) else state.TOOL_OPEN

    text = _CALL_TAG_PIPE_RE.sub(_replace, text)
    return _CALL_TAG_VARIANT_RE.sub(_replace, text)


def _convert_invoke_blocks(text: str) -> str:
    """Konversi blok invoke name=... berisi parameter name=... ke blok resmi."""
    if "<invoke" not in text:
        return text
    out = []
    pos = 0
    while True:
        match = _INVOKE_OPEN_RE.search(text, pos)
        if not match:
            out.append(text[pos:])
            break
        name = _attr_name(match.group(1))
        closer = _INVOKE_CLOSE_RE.search(text, match.end())
        if closer is None:
            body = text[match.end():]
            arguments = _parse_tag_params(body, value_terminators=(state.TOOL_CLOSE,))
            out.append(text[pos:match.start()])
            if name and arguments:
                out.append(_mk_tool_call_block(name, arguments))
                pos = len(text)
            else:
                out.append(text[match.start():match.end()])
                pos = match.end()
            continue
        body = text[match.end():closer.start()]
        arguments = _parse_tag_params(body)
        out.append(text[pos:match.start()])
        if name and arguments:
            out.append(_mk_tool_call_block(name, arguments))
        else:
            out.append(text[match.start():closer.end()])
        pos = closer.end()
    return "".join(out)


def _convert_function_blocks(text: str) -> str:
    """Konversi blok function=NAME berisi parameter=KEY ke blok resmi.

    Penutup function sering HILANG di data nyata; kalau begitu dipakai penutup
    blok resmi atau akhir teks sebagai batas, dan sisa JSON terpotong yang
    menempel di ekor nilai dipangkas (lihat _JSON_TAIL_JUNK_RE).
    """
    if "<function=" not in text and "<function name" not in text:
        return text
    out = []
    pos = 0
    while True:
        match = _FUNCTION_OPEN_RE.search(text, pos)
        if not match:
            out.append(text[pos:])
            break
        closer = _FUNCTION_CLOSE_RE.search(text, match.end())
        body_end = closer.start() if closer else len(text)
        block_end = closer.end() if closer else len(text)
        if closer is None:
            legacy = text.find(state.TOOL_CLOSE, match.end())
            if legacy != -1:
                body_end = legacy
                block_end = legacy + len(state.TOOL_CLOSE)
        body = text[match.end():body_end]
        arguments = _parse_tag_params(
            body,
            value_terminators=() if closer else (state.TOOL_CLOSE,),
        )
        if arguments:
            arguments = {
                key: _JSON_TAIL_JUNK_RE.sub("", value)
                for key, value in arguments.items()
            }
        out.append(text[pos:match.start()])
        if arguments:
            out.append(_mk_tool_call_block(match.group(1), arguments))
        else:
            out.append(text[match.start():block_end])
        pos = block_end
    return "".join(out)


def _drop_unmatched_call_tags(text: str) -> str:
    """Buang tag pembuka/penutup blok resmi yang tidak berpasangan.

    Penutup liar muncul dari keluarga sintaks asing (penutup plural atau
    penutup ganda yang sudah dinormalkan), sedangkan pembuka liar muncul dari
    tag pembungkus yang penutupnya hilang. Sisa tag mentah ini sebelumnya
    bocor ke layar user sebagai teks sampah.

    Pembuka yang tidak berpasangan hanya dibuang bila TIDAK langsung diikuti
    '{' -- blok ber-JSON-tapi-invalid sengaja dibiarkan terlihat user sebagai
    bukti error (lihat konvensi strip_tool_call_blocks).
    """
    if state.TOOL_OPEN not in text and state.TOOL_CLOSE not in text:
        return text
    pattern = re.compile(
        re.escape(state.TOOL_OPEN) + "|" + re.escape(state.TOOL_CLOSE)
    )
    events = list(pattern.finditer(text))
    if not events:
        return text
    depth = 0
    drops = []
    pending = []
    for event in events:
        if event.group(0) == state.TOOL_OPEN:
            depth += 1
            pending.append(event)
        elif depth > 0:
            depth -= 1
            pending.pop()
        else:
            drops.append((event.start(), event.end()))
    for event in pending:
        rest = text[event.end():].lstrip()
        if not rest.startswith("{"):
            drops.append((event.start(), event.end()))
    if not drops:
        return text
    out = text
    for start, end in reversed(drops):
        out = out[:start] + out[end:]
    return out


def _normalize_alt_forms(text: str, drop_stray_tags: bool = True) -> str:
    """Normalkan SEMUA keluarga sintaks asing ke blok resmi ber-JSON.

    `drop_stray_tags=False` dipakai saat normalisasi dijalankan per-potongan
    teks (lihat `_convert_alt_tool_call_syntax`): pasangan tag bisa terbelah
    antar potongan, jadi pembuangan tag liar harus dilakukan sekali di akhir.
    """
    lowered = text.lower()
    if (
        "invoke" not in lowered
        and "function" not in lowered
        and "\uff5c" not in text
        and "call" not in lowered
    ):
        return text
    text = _strip_dsml_marks(text)
    text = _normalize_call_tag_variants(text)
    text = _convert_invoke_blocks(text)
    text = _convert_function_blocks(text)
    if drop_stray_tags:
        text = _drop_unmatched_call_tags(text)
    return text


def _protect_valid_tool_call_blocks(text: str):
    """Ganti blok tool_call yang JSON-nya SUDAH valid dengan placeholder.

    Blok resmi yang sudah bisa dieksekusi tidak boleh disentuh normalizer:
    ISI STRING argumennya bisa memuat teks mirip tag (mis. model menulis ulang
    kode yang berisi `<function=...>` atau `<parameter ...>`), dan menyentuh
    isi itu merusak JSON yang tadinya valid (escape berubah -> PARSE_ERROR).
    Spans yang dilindungi di sini PERSIS spans yang dieksekusi, karena sama-
    sama memakai `json_repair._iter_tool_call_blocks`.

    Mengembalikan `(masked_text, {token: blok_asli})`.
    """
    from .. import json_repair as json_repair_mod  # lazy: hindari siklus impor

    spans = []
    for start, end, raw_json in json_repair_mod._iter_tool_call_blocks(text):
        name, _args = json_repair_mod._parse_raw_json(raw_json)
        if name in (None, "PARSE_ERROR"):
            continue
        spans.append((start, end, text[start:end]))

    if not spans:
        return text, {}

    out = []
    mapping = {}
    pos = 0
    for index, (start, end, block) in enumerate(spans):
        token = "\x00%d\x00" % index
        mapping[token] = block
        out.append(text[pos:start])
        out.append(token)
        pos = end
    out.append(text[pos:])
    return "".join(out), mapping


def _convert_alt_tool_call_syntax(text: str) -> str:
    """Ubah semua blok tool_call format ALTERNATIF di text menjadi blok resmi
    state.TOOL_OPEN + JSON + state.TOOL_CLOSE.

    Tiga tahap:
      1. format alternatif internal (lihat ALT_TOOL_CALL_RE) -- diproses lebih
         dulu supaya penandanya belum ikut dinormalkan oleh tahap kedua;
      2. blok resmi yang sudah ber-JSON VALID dilindungi (lihat
         _protect_valid_tool_call_blocks) supaya isi string argumennya tidak
         ikut ditulis ulang -- blok itu sudah akan dieksekusi apa adanya;
      3. keluarga sintaks model lain: DSML, XML invoke, function=, tag varian
         spasi (lihat _normalize_alt_forms).

    Kalau tidak ada blok format alternatif ditemukan, text dikembalikan apa
    adanya (no-op) -- aman dipanggil untuk SETIAP balasan model.
    """
    if not text:
        return text

    if "<|tool_call>" in text:

        def _replace(match: "re.Match") -> str:
            alt_name = match.group(1)
            raw_args = match.group(2)
            arguments = _parse_alt_tool_call_args(raw_args)
            return _mk_tool_call_block(alt_name, arguments)

        text = state.ALT_TOOL_CALL_RE.sub(_replace, text)

    masked, protected = _protect_valid_tool_call_blocks(text)
    masked = _normalize_alt_forms(masked)
    if not protected:
        return masked
    for token, block in protected.items():
        masked = masked.replace(token, block)
    return masked
