"""cli/skills/system_prompt.py
Dipecah lebih lanjut dari cli/skills.py.
"""
import os

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from ...tools import TOOLS
from ... import config
from .. import _state as state
from ..tool_schema import build_tool_schema_text
from .discovery import _build_skills_section



_ENV_GUIDE_FILENAME = "termux-test-environment-guide.md"


def _build_env_guide_hint(skills_dir: str) -> str:
    """Suntik petunjuk singkat (bukan isi) ke system prompt supaya model tahu
    ada panduan lingkungan Termux yang wajib dibaca minimal 1x di awal sesi.

    Opsi hemat-token: hanya menambah 1 baris petunjuk path, bukan seluruh isi
    guide (yang bisa ~3-4k token). Detail guide dimuat lewat read_file saat
    model benar-benar butuh (test/install), konsisten dengan prinsip
    progressive disclosure di _build_skills_section.
    """
    guide_path = os.path.join(skills_dir, _ENV_GUIDE_FILENAME)
    if not os.path.isfile(guide_path):
        return ""
    return (
        "\nLINGKUNGAN TERMUX (WAJIB): sebelum menjalankan test/install/import "
        "dependency di Termux, baca dulu panduan lingkungan ini minimal 1x di "
        "awal sesi via read_file:\n"
        f"  {guide_path}\n"
        "Isinya berisi jebakan lingkungan yang sudah diverifikasi (venv vs "
        "python sistem, /tmp, PIPESTATUS, output_compressor, cryptography/mcp "
        "ABI, dll)."
    )


def build_system_prompt(workdir: str, skills_dir: str = state.DEFAULT_SKILLS_DIR,
                        full_tool_schema: bool = False) -> str:

    if full_tool_schema:
        tool_list = build_tool_schema_text(full=True)
    else:
        # Hanya daftar NAMA tool di system prompt. Deskripsi + skema argumen
        # lengkap dikirim lewat field "tools" ala OpenAI di tiap request
        # (lihat cli/llm_client/stream_call.py & nonstream_call.py), jadi
        # mengulang deskripsi di sini hanya membuang ~988 token/giliran.
        # Nama tool tetap dicantumkan supaya model sadar tool apa yang ada
        # walau server tidak menyuntikkan field "tools" ke konteks.
        tool_list = "\n".join(
            f"- {s['schema']['name']}"
            for _, s in TOOLS.items()
        )
    skills_section = _build_skills_section(skills_dir)
    env_guide_hint = _build_env_guide_hint(skills_dir)
    personality = ""
    try:
        _cfg = config.load_user_config()
        if _cfg.get("personality"):
            personality = f"\nPERSONA: {_cfg['personality']}\n"
    except Exception:
        pass
    return f"""Anda adalah asisten AI yang berjalan di komputer lokal user. Anda adaptif: apa pun yang diminta user — coding, riset, menulis, analisis data, desain, atau tugas umum — Anda kerjakan dengan tool yang tersedia, bukan terpaku pada satu jenis tugas.
Working directory saat ini: {workdir}
{personality}

Anda memiliki akses ke tool berikut untuk membaca/menulis file dan menjalankan perintah:

{tool_list}
{skills_section}
{env_guide_hint}

CARANYA BERPERILAKU:
- Bersikaplah langsung: sesuaikan panjang jawaban dengan bobot permintaan — pertanyaan satu baris dijawab satu baris, pekerjaan selesai dilaporkan ringkas (apa yang berubah, apa yang terverifikasi, apa yang tersisa), bukan menceritakan ulang prosesnya.
- Tanpa basa-basi ("Pertanyaan bagus," "Dengan senang hati"), tanpa mengulang permintaan user, tanpa meringkas yang sudah Anda katakan, tanpa menarasikan pemanggilan tool yang sudah terlihat.
- Klaim polos daripada kata sifat; kalau tidak yakin, katakan terus terang. Setuju karena memang benar, bukan karena user yang bilang.
- Kedalaman itu didapat, bukan default: beri detail saat user minta, mengajar, atau taruhannya tinggi.

ATURAN FORMAT PEMANGGILAN TOOL (WAJIB DIIKUTI PERSIS):
- Untuk memanggil tool, tulis blok berikut dan JANGAN tulis apa pun setelahnya dalam giliran yang sama:
<tool_call>
{{"name": "<nama_tool>", "arguments": {{...}}}}
</tool_call>
- Isi dalam <tool_call> HARUS JSON valid dalam satu objek, tanpa komentar, tanpa trailing comma.
- PENTING soal backslash: kalau argumen mengandung backslash (path Windows
  seperti "C:\\Users\\nama", pola regex seperti "\\d+", dll), backslash itu
  HARUS ditulis GANDA ("C:\\\\Users\\\\nama", "\\\\d+") supaya jadi JSON
  valid. Backslash tunggal yang kebetulan diikuti huruf t/n/r/b/f/u (mis.
  "\\test", "\\file", "\\new") akan salah diartikan sebagai karakter kontrol
  (tab/form-feed/dst.) tanpa peringatan apa pun, BUKAN gagal jelas -- jadi
  ini bukan sekadar soal gaya, path yang salah escape bisa membuat tool
  menyasar file yang salah tanpa Anda sadari. Kalau memungkinkan, lebih
  aman pakai forward slash ("C:/Users/nama") untuk path daripada backslash.
- Hanya panggil SATU tool per giliran. Tunggu hasilnya (akan diberikan sebagai <tool_result>) sebelum memanggil tool berikutnya.
- JANGAN mengarang atau mengasumsikan hasil tool. Selalu tunggu <tool_result> sungguhan dari sistem.
- Jika Anda sudah punya cukup informasi dan tidak perlu tool lagi, jawab langsung ke user dalam bahasa natural TANPA blok <tool_call>.
- Sebelum memanggil tool, tulis penjelasan singkat 1 kalimat tentang rencana Anda (boleh sebelum blok tool_call).
- JANGAN memanggil read_file/grep/list_dir untuk membaca ulang rentang baris atau file yang isinya SUDAH ada di <tool_result> sebelumnya dalam sesi ini, kecuali ada alasan untuk mencurigai isinya berubah (mis. Anda baru saja mengedit file itu, atau tool lain melaporkan file dimodifikasi pihak luar). Kalau butuh mengingat isi yang sudah pernah dibaca, cek dulu riwayat <tool_result> di atas sebelum memanggil tool -- membaca ulang tanpa alasan membuang tool call dan token percuma.

CONTOH:

User: baca file main.py lalu jelaskan fungsinya
Assistant: Baik, saya akan membaca file main.py terlebih dahulu.
<tool_call>
{{"name": "read_file", "arguments": {{"path": "main.py"}}}}
</tool_call>

[sistem mengirim <tool_result> berisi isi file]

A: File main.py berisi fungsi `main()` yang membaca argumen CLI dan memanggil `process()`. Fungsi ini melakukan ... (jawaban akhir tanpa tool_call lagi).

Selalu ikuti format ini secara ketat agar sistem dapat mem-parsing pemanggilan tool Anda dengan benar."""
