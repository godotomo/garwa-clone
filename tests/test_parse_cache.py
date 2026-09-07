"""test_parse_cache.py
Unit test untuk P3 incremental parse cache di garwa/repo_map.py.

Prinsip:
  - Test perilaku parse_with_cache & invalidate_tree_cache baik saat
    tree-sitter tersedia maupun tidak (fallback None).
  - Test bahwa cache menyimpan per-path dan hash konten, serta LRU eviction.
  - Test snippet_for_position fallback (regex/baris) tetap berfungsi ketika
    tree-sitter tidak tersedia (tidak boleh crash).
"""

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import garwa.repo_map as rm  # noqa: E402


def test_parse_with_cache_returns_none_when_ts_unavailable():
    """Kalau tree-sitter tak tersedia, parse_with_cache harus (None,None,None)
    tanpa exception, dan tidak boleh crash untuk path apa pun."""
    if rm._TS_AVAILABLE:
        return  # skip bila tree-sitter terpasang — diuji jalur TS di bawah
    fd, path = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("def foo():\n    return 1\n")
        tree, src, text = rm.parse_with_cache(path, "python")
        assert tree is None
        assert src is None
        assert text is None
    finally:
        os.remove(path)


def test_invalidate_tree_cache_never_crashes():
    """invalidate_tree_cache harus aman dipanggil untuk path apa pun, termasuk
    yang belum pernah di-cache."""
    rm.invalidate_tree_cache("/nonexistent/path/xyz.py")
    rm.invalidate_tree_cache("relative.py")
    # tidak ada exception = lolos


def test_snippet_fallback_works_without_ts():
    """snippet_for_position harus selalu mengembalikan string (tidak crash),
    baik pakai tree-sitter maupun fallback baris."""
    fd, path = tempfile.mkstemp(suffix=".py")
    try:
        content = "def foo():\n    x = 1\n    return x\n"
        with os.fdopen(fd, "w") as f:
            f.write(content)
        s = rm.snippet_for_position(path, 2)
        assert isinstance(s, str)
        assert "foo" in s or "x = 1" in s  # nama/konteks ada
    finally:
        os.remove(path)


def test_snippet_missing_file_returns_error_string():
    s = rm.snippet_for_position("/nonexistent/missing.py", 1)
    assert isinstance(s, str)
    assert "Gagal" in s or "tidak" in s


def test_parse_with_cache_caches_when_ts_available():
    """Kalau tree-sitter tersedia: panggil dua kali konten sama harus
    mengembalikan tree yang sama (cache hit, tidak parse ulang)."""
    if not rm._TS_AVAILABLE:
        return
    fd, path = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("def foo():\n    return 1\n")
        tree1, _, _ = rm.parse_with_cache(path, "python")
        tree2, _, _ = rm.parse_with_cache(path, "python")
        assert tree1 is not None
        assert tree1 is tree2  # cache hit — objek Tree sama
    finally:
        os.remove(path)
        rm.invalidate_tree_cache(path)


def test_parse_with_cache_incremental_when_ts_available():
    """Kalau tree-sitter tersedia: edit konten lalu parse ulang harus tetap
    menghasilkan tree valid (incremental parse dipakai)."""
    if not rm._TS_AVAILABLE:
        return
    fd, path = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("def foo():\n    return 1\n")
        tree1, _, _ = rm.parse_with_cache(path, "python")
        assert tree1 is not None
        # ubah konten
        with open(path, "w") as f:
            f.write("def foo():\n    x = 2\n    return x\n")
        tree2, _, text = rm.parse_with_cache(path, "python")
        assert tree2 is not None
        assert "x = 2" in text
        assert tree2 is not tree1  # objek baru setelah konten berubah
    finally:
        os.remove(path)
        rm.invalidate_tree_cache(path)


def test_parse_with_cache_handles_rust_panic():
    """pyo3 PanicException (panic Rust) adalah BaseException, bukan Exception.
    parse_with_cache & snippet_for_position harus menangkapnya dan fallback
    ke regex, tidak boleh crash."""
    if not rm._TS_AVAILABLE:
        return
    orig = rm._get_parser
    orig_flag = rm._TS_AVAILABLE
    rm._TS_AVAILABLE = True

    def boom(lang):
        raise BaseException("simulated rust panic: rustls-platform-verifier")

    rm._get_parser = boom
    fd, path = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("def foo():\n    return 1\n")
        tree, src, text = rm.parse_with_cache(path, "python")
        assert tree is None
        assert src is None
        assert text is None
        # snippet fallback regex tetap jalan
        s = rm.snippet_for_position(path, 1)
        assert isinstance(s, str)
        assert "foo" in s
    finally:
        rm._get_parser = orig
        rm._TS_AVAILABLE = orig_flag
        os.remove(path)


def test_get_parser_python_works_when_grammar_installed():
    """Kalau grammar individual python terinstall, _get_parser('python') harus
    mengembalikan parser yang bisa parse AST (bukan None)."""
    if not rm._TS_AVAILABLE:
        return
    try:
        import tree_sitter_python  # noqa: F401
    except Exception:
        return  # grammar tidak terinstall di env ini
    p = rm._get_parser("python")
    assert p is not None
    tree = p.parse(b"def foo():\n    return 1\n")
    assert tree is not None
    assert tree.root_node.type in ("module", "file", "program")


def test_get_parser_unknown_lang_returns_none():
    """Bahasa yang tidak didukung grammar mana pun harus None (bukan crash)."""
    p = rm._get_parser("definitely_not_a_real_lang_xyz")
    assert p is None


def test_lru_eviction():
    """Cache dibatasi; akses banyak path harus menyingkirkan yang paling lama."""
    if not rm._TS_AVAILABLE:
        return
    old_max = rm._TS_TREE_CACHE_MAX
    rm._TS_TREE_CACHE_MAX = 3
    try:
        paths = []
        for i in range(5):
            fd, path = tempfile.mkstemp(suffix=".py")
            with os.fdopen(fd, "w") as f:
                f.write(f"def f{i}():\n    return {i}\n")
            paths.append(path)
            rm.parse_with_cache(path, "python")
        # hanya 3 terakhir yang bertahan
        assert len(rm._ts_tree_cache) <= 3
        for p in paths[:2]:
            assert p not in rm._ts_tree_cache
    finally:
        rm._TS_TREE_CACHE_MAX = old_max
        for p in paths:
            rm.invalidate_tree_cache(p)
            if os.path.exists(p):
                os.remove(p)
