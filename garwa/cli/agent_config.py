"""cli/agent_config.py
Dataclass `AgentConfig` -- pengganti `argparse.Namespace` untuk menjalankan
agent loop (dan nantinya sub-agent in-process).

Alasan refactor (poin #1 dari rencana rilis v0.5.0):
- `argparse.Namespace` adalah objek ad-hoc tanpa kontrak tipe. Setiap pemakai
  `run_agent_loop` harus tahu atribut mana yang harus ada, dan sub-agent
  (yang tidak lewat parser CLI) tidak punya cara bersih untuk membuat konfig.
- `AgentConfig` memberi kontrak eksplisit (field bertipe, default jelas) dan
  bisa dibuat tanpa parser -- penting untuk testability dan sub-agent.

Kompatibilitas:
- `run_agent_loop` (dan callers lain) masih menerima `args` yang bisa berupa
  `AgentConfig` ATAU `argparse.Namespace`. Helper `coerce_agent_config()`
  mengonversi Namespace -> AgentConfig di dalam, sehingga refactor ini
  NON-DESTRUKTIF: kode lama yang masih meneruskan Namespace tetap bekerja.
- `AgentConfig.from_namespace()` menyalin semua field yang dikenal dari
  Namespace (argparse). Field yang tidak ada di Namespace memakai default
  dataclass.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from dataclasses import dataclass, field

from .. import db as dbmod
from . import _state as state


@dataclass
class AgentConfig:
    """Konfigurasi lengkap untuk satu giliran agent (atau satu sub-agent).

    Semua field memakai nama yang sama dengan flag CLI di main.py supaya
    konversi dari `argparse.Namespace` (via `from_namespace`) trivial dan
    tidak ambigu. Field yang TIDAK dipakai oleh `run_agent_loop` tetap
    disertakan supaya `AgentConfig` bisa dibuat dari Namespace penuh dan
    diteruskan ke mode auto/overnight tanpa kehilangan informasi.
    """

    # --- Server model ---
    url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.6

    # --- Tool / environment ---
    skills_dir: str = ""
    workdir: str = ""
    no_sandbox: bool = False
    auto_approve: bool = False
    max_tool_iters: int = 100
    max_image_mb: float = 8.0

    # --- Context management ---
    context_window: int = 0
    reserve_for_response: int = 0
    summarize_threshold_ratio: float = 0.0
    keep_tail_messages: int = 0

    # --- Streaming / schema ---
    no_stream: bool = False
    full_tool_schema_text: bool = False
    skip_server_check: bool = False

    # --- Persistence ---
    db_path: str = ""
    resume: str | None = None
    list_sessions: bool = False
    session_title: str | None = None

    # --- Mode auto / overnight ---
    auto: bool = False
    overnight: bool = False
    task: str | None = None
    tasks_file: str | None = None
    overnight_log: str | None = None
    stop_on_error: bool = False
    plan_file: str | None = None
    repeat_until_done: bool = False
    max_repeats: int = 50

    # --- MCP ---
    mcp_config: str | None = None

    # --- Debug ---
    debug: bool = False

    # --- Summarization (poin #4 rilis v0.5.0) ---
    # Model terpisah untuk summarization riwayat & catatan. Kalau kosong,
    # dipakai `model` utama (perilaku lama). Tujuan: hemat biaya dengan
    # memakai model murah untuk ringkasan, model kuat untuk giliran utama.
    summarize_model: str = ""

    # --- Sub-agent (khusus; TIDAK ada di argparse CLI) ---
    # Role prompt untuk sub-agent. Kalau diisi, system_content yang dipakai
    # agent loop adalah role prompt ini (bukan system prompt global). Dipakai
    # oleh tool `spawn_agent` untuk membuat sub-agent dengan identitas sendiri.
    role_prompt: str | None = None
    # Nama sub-agent (untuk label/spinner). Default "sub".
    sub_name: str = "sub"

    def __post_init__(self) -> None:
        """Isi default yang bergantung pada runtime/state bila field kosong.

        Memakai nilai `0`/`""` sebagai penanda "belum diset" supaya
        `from_namespace` bisa membedakan field yang benar-benar ada di
        Namespace (nilai aslinya, termasuk 0/False) dari field yang tidak
        ada di Namespace (fallback ke default di sini).
        """
        if not self.url:
            self.url = _env("LLAMA_URL", "http://127.0.0.1:8080")
        if not self.model:
            self.model = _env("LLAMA_MODEL", "")
        if not self.api_key:
            self.api_key = _env("LLAMA_API_KEY", "")
        if not self.skills_dir:
            self.skills_dir = state.DEFAULT_SKILLS_DIR
        if not self.workdir:
            self.workdir = os.getcwd()
        if not self.db_path:
            self.db_path = dbmod.DEFAULT_DB_PATH
        if not self.context_window:
            self.context_window = _env_int("GARWA_CONTEXT_WINDOW", 32768)
        if not self.reserve_for_response:
            self.reserve_for_response = _env_int("GARWA_RESERVE_FOR_RESPONSE", 4096)
        if not self.summarize_threshold_ratio:
            self.summarize_threshold_ratio = _env_float("GARWA_SUMMARIZE_THRESHOLD_RATIO", 0.75)
        if not self.keep_tail_messages:
            self.keep_tail_messages = _env_int("GARWA_KEEP_TAIL_MESSAGES", 12)

    # --- Konversi ---

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> "AgentConfig":
        """Buat AgentConfig dari argparse.Namespace (hasil parser CLI).

        Hanya field yang ADA di Namespace yang disalin; sisanya memakai
        default dataclass (diisi di __post_init__). Dengan begitu Namespace
        lama yang tidak punya field sub-agent tetap bisa dikonversi.
        """
        known = {f.name for f in dataclasses.fields(cls)}
        vals = {}
        for k in known:
            if hasattr(ns, k):
                vals[k] = getattr(ns, k)
        return cls(**vals)

    def as_namespace(self) -> argparse.Namespace:
        """Kembalikan representasi argparse.Namespace (untuk kode lama yang
        masih menuntut Namespace, mis. helper yang memodifikasi args)."""
        return argparse.Namespace(**{f.name: getattr(self, f.name)
                                     for f in dataclasses.fields(self)})


def coerce_agent_config(args) -> AgentConfig:
    """Konversi `args` (bisa AgentConfig atau argparse.Namespace) ke AgentConfig.

    - Kalau sudah AgentConfig, dikembalikan apa adanya (identity).
    - Kalau Namespace, dikonversi via `AgentConfig.from_namespace`.
    Ini dipakai di `run_agent_loop` supaya menerima keduanya tanpa merusak
    callers lama.
    """
    if isinstance(args, AgentConfig):
        return args
    if isinstance(args, argparse.Namespace):
        return AgentConfig.from_namespace(args)
    raise TypeError(
        f"args harus berupa AgentConfig atau argparse.Namespace, "
        f"dapat: {type(args).__name__}"
    )


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
