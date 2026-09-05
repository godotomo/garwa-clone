"""Regression tests untuk build_api (jobbot/executor.py).

Memastikan deliverable FastAPI yang di-generate:
  1. Tidak mengandung literal '{{' / '}}' yang salah (bug escaping f-string).
  2. Semua file .py deliverable valid secara sintaks (kompilasi).
  3. Struktur kunci (lazy engine, get_db) benar agar test hermetic.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jobbot.executor import build_api
from jobbot.models import Job


def _build(tmp_path):
    import jobbot.executor as executor
    # Arahkan output ke temp dir agar tidak mengotori deliverables/.
    executor.DELIVERABLES_DIR = str(tmp_path)
    job = Job(
        platform="test", job_id="regression", title="Regression Test API",
        company="Acme", category="Software Engineering",
        description="Build a production REST API",
    )
    return build_api(job)


def test_build_api_no_bad_braces(tmp_path):
    """Tidak boleh ada literal '{{'/'}}' di file .py deliverable (bug escaping)."""
    result = _build(tmp_path)
    root = result["path"]
    for f in result["files"]:
        rel = f["path"] if isinstance(f, dict) else f
        if not str(rel).endswith(".py"):
            continue
        path = os.path.join(root, rel)
        content = open(path, encoding="utf-8").read()
        # '{{' hanya legal di dalam template .mako, bukan file .py biasa.
        assert "{{" not in content, f"literal '{{' ditemukan di {path}"
        assert "}}" not in content, f"literal '}}' ditemukan di {path}"


def test_build_api_py_files_compile(tmp_path):
    """Semua file .py deliverable harus kompilasi tanpa error."""
    import py_compile
    result = _build(tmp_path)
    root = result["path"]
    for f in result["files"]:
        rel = f["path"] if isinstance(f, dict) else f
        if not str(rel).endswith(".py"):
            continue
        path = os.path.join(root, rel)
        py_compile.compile(str(path), doraise=True)


def test_build_api_lazy_engine(tmp_path):
    """app/db.py harus pakai lazy engine (get_engine), bukan eager module-level."""
    result = _build(tmp_path)
    db_path = os.path.join(result["path"], "app", "db.py")
    content = open(db_path, encoding="utf-8").read()
    assert "def get_engine" in content, "get_engine() tidak ditemukan"
    # Tidak boleh ada `engine = create_async_engine(...)` di level module.
    assert "engine = create_async_engine" not in content, \
        "engine eager module-level masih ada (harus lazy)"


def test_build_api_lifespan_no_create_all(tmp_path):
    """main.py lifespan tidak boleh memanggil create_all (itu tugas migrasi)."""
    result = _build(tmp_path)
    main_path = os.path.join(result["path"], "app", "main.py")
    content = open(main_path, encoding="utf-8").read()
    assert "metadata.create_all" not in content, \
        "lifespan tidak boleh memanggil create_all (harus via Alembic migration)"


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        test_build_api_no_bad_braces(tmp)
        test_build_api_py_files_compile(tmp)
        test_build_api_lazy_engine(tmp)
        test_build_api_lifespan_no_create_all(tmp)
    print("All build_api regression tests passed")
