"""Unit test untuk peningkatan repo_map (P1-P4) — references AST, graph
PageRank dengan personalization, distribusi rank ke definisi, binary search
token budget, dan filter file penting (mirip Aider)."""

import os
import tempfile

import garwa.repo_map as rm  # noqa: E402


def _make_repo():
    """Buat repo kecil: util.py didefinisikan helper, main.py memakai helper."""
    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, "pkg"))
    with open(os.path.join(tmp, "pkg", "util.py"), "w") as f:
        f.write("def helper(x):\n    return x * 2\n\ndef other():\n    return 1\n")
    with open(os.path.join(tmp, "pkg", "main.py"), "w") as f:
        f.write("from pkg.util import helper\n\ndef run():\n    return helper(21)\n")
    with open(os.path.join(tmp, "README.md"), "w") as f:
        f.write("# Demo project\nThis is a demo.\n")
    return tmp


def test_collect_identifiers_ast():
    """_collect_identifiers_treesitter harus menangkap identifier AST, bukan
    yang ada di string literal."""
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "a.py")
    with open(p, "w") as f:
        f.write('x = 1\ny = "helper_not_real"\nz = x + 1\n')
    with open(p, "rb") as f:
        raw = f.read()
    idents = rm._collect_identifiers_treesitter(p, "python", raw)
    assert idents is not None
    # 'helper_not_real' ada di string literal -> tidak boleh masuk
    assert "helper_not_real" not in idents
    assert "x" in idents
    assert "z" in idents


def test_build_graph_ranked_definitions():
    """build_graph_and_rank harus mendeteksi referensi lintas file dan
    menghasilkan ranked_definitions dengan helper dari util.py ter-ranking."""
    tmp = _make_repo()
    fdefs, frefs, ranked, ranks = rm.build_graph_and_rank(tmp, personalize={"pkg/main.py"})
    # Referensi AST dari main.py harus memuat helper.
    assert "helper" in frefs.get("pkg/main.py", set())
    # ranked_definitions: helper di util.py harus ada (dirujuk lintas file).
    ranked_keys = [(rel, ident) for rel, ident, _ in ranked]
    assert ("pkg/util.py", "helper") in ranked_keys


def test_pagerank_personalization():
    """_power_iteration_pagerank dengan personalization harus memberi skor
    lebih tinggi pada node yang dipersonalisasi."""
    nodes = ["a", "b", "c"]
    edges = {("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "a"): 1.0}
    r = rm._power_iteration_pagerank(nodes, edges, personalization={"a": 100.0})
    assert r["a"] > r["b"] and r["a"] > r["c"]


def test_pagerank_dangling():
    """Node tanpa out-edge (dangling) harus mendistribusikan rank, tidak crash."""
    nodes = ["a", "b"]
    edges = {("a", "b"): 2.0}  # b dangling (tanpa out-edge)
    r = rm._power_iteration_pagerank(nodes, edges)
    assert "a" in r and "b" in r
    assert abs(sum(r.values()) - 1.0) < 1e-6


def test_generate_includes_important_file():
    """generate harus menyertakan README.md (file penting) walau tanpa simbol."""
    tmp = _make_repo()
    out = rm.generate(tmp, token_budget=200, personalize_files={"pkg/main.py"})
    assert "README.md" in out


def test_generate_binary_search_budget():
    """generate dengan budget kecil harus tetap menghasilkan map yang tidak
    melebihi budget (tidak crash, header selalu ada)."""
    tmp = _make_repo()
    out = rm.generate(tmp, token_budget=10, personalize_files={"pkg/main.py"})
    assert isinstance(out, str)
    assert out.strip() != ""


def test_filter_important_files():
    """_filter_important_files harus mengenali README.md & Makefile."""
    assert "README.md" in rm._filter_important_files(["README.md", "pkg/util.py"])
    assert "Makefile" in rm._filter_important_files(["Makefile", "src/main.py"])
    assert "pkg/util.py" not in rm._filter_important_files(["pkg/util.py"])


def test_extract_defs_none_lang():
    """extract_defs dengan lang=None (file penting) harus return []."""
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "README.md")
    with open(p, "w") as f:
        f.write("# hi\n")
    assert rm.extract_defs(p, None) == []


def test_preview_text():
    """_preview_text harus mengambil baris-baris pertama file."""
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "README.md")
    with open(p, "w") as f:
        f.write("# Title\nbody line\n\nskip\n")
    lines = rm._preview_text(tmp, "README.md")
    assert "# Title" in lines
    assert "body line" in lines
