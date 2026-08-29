"""
repo_map.py
Peta struktur repo yang hemat token, terinspirasi dari fitur "repo map"
di Aider (https://aider.chat/2023/10/22/repomap.html):

  1. Parse tiap file source dengan tree-sitter -> ekstrak simbol definisi
     (fungsi/class/struct/dll) beserta baris & tanda tangannya.
  2. Bangun graph berarah: file A -> file B kalau A menyebut identifier
     yang didefinisikan di B (referensi lintas file).
  3. Ranking file/simbol pakai PageRank di atas graph tsb (personalized
     sedikit: file yang baru dibaca/diedit di sesi ini diberi bobot lebih).
  4. Pilih simbol berperingkat tertinggi sampai token budget habis
     (binary search sederhana), lalu render sebagai teks ringkas.

Dependency opsional:
- tree_sitter + tree_sitter_language_pack (atau tree_sitter_languages):
  kalau tidak terinstall, repo_map otomatis fallback ke ekstraksi
  berbasis regex per bahasa (lebih kasar, tapi tetap berguna & tanpa
  dependency tambahan).
- Ranking PageRank diimplementasikan manual (power iteration) supaya
  tidak perlu networkx.

Install (opsional, disarankan untuk hasil lebih akurat & multi-bahasa):
    pip install tree-sitter tree-sitter-language-pack --break-system-packages
"""

import os
import re
from collections import defaultdict

from . import db as dbmod


_TS_AVAILABLE = False
_get_parser = None

try:
    from tree_sitter_language_pack import get_parser as _get_parser  # type: ignore
    _TS_AVAILABLE = True
except Exception:
    try:
        from tree_sitter_languages import get_parser as _get_parser  # type: ignore
        _TS_AVAILABLE = True
    except Exception:
        _TS_AVAILABLE = False

EXT_LANG = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "c_sharp",
    ".sh": "bash",
    ".sol": "solidity",
    ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift",
    ".dart": "dart",
    ".lua": "lua",
    ".scala": "scala",
    ".ex": "elixir", ".exs": "elixir",
    ".hs": "haskell",
    ".r": "r", ".R": "r",
}

DEF_NODE_TYPES = {
    "function_definition", "function_declaration", "function_item",
    "method_definition", "method_declaration",
    "class_definition", "class_declaration",
    "struct_item", "struct_specifier",
    "impl_item", "interface_declaration", "trait_item",
    "type_declaration", "enum_declaration", "enum_item",
    # Solidity (tree-sitter-solidity via tree_sitter_language_pack):
    "contract_declaration", "library_declaration",
    "struct_declaration",
    "event_definition", "modifier_definition", "constructor_definition",
    # Kotlin:
    "object_declaration",
    # Swift:
    "protocol_declaration", "protocol_function_declaration", "init_declaration",
    # Dart:
    "mixin_declaration", "extension_declaration", "function_signature",
    # Scala:
    "trait_definition", "object_definition", "type_definition",
    # Lua:
    # (function_declaration sudah ada; function_definition/assignment ditangani
    #  oleh custom walker agar namanya akurat)
    # Haskell:
    "data_type", "type_synomym", "newtype", "signature",
}

# Bahasa yang diekstrak pakai walker khusus (bukan DEF_NODE_TYPES generik)
# karena struktur AST-nya tidak punya field "name"/"identifier" langsung.
CUSTOM_WALKER_LANGS = {"elixir", "haskell", "r", "lua"}
NAME_FIELDS = ("name", "declarator")

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
                "build", ".mypy_cache", ".pytest_cache", ".idea", ".vscode", "target"}

REGEX_DEFS = {
    "python": re.compile(r"^[ \t]*(?:async\s+)?def\s+(\w+)\s*\(.*?\)\s*:", re.MULTILINE),
    "python_class": re.compile(r"^[ \t]*class\s+(\w+)\b", re.MULTILINE),
    "javascript": re.compile(
        r"^[ \t]*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(|"
        r"^[ \t]*(?:export\s+)?class\s+(\w+)\b|"
        r"^[ \t]*const\s+(\w+)\s*=\s*(?:async\s*)?\(.*?\)\s*=>",
        re.MULTILINE,
    ),
    "go": re.compile(r"^func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(", re.MULTILINE),
    "rust": re.compile(r"^[ \t]*(?:pub\s+)?fn\s+(\w+)\s*\(|^[ \t]*(?:pub\s+)?struct\s+(\w+)\b", re.MULTILINE),
    "java": re.compile(r"^[ \t]*(?:public|private|protected|static|\s)*\w[\w<>\[\]]*\s+(\w+)\s*\([^;{]*\)\s*\{", re.MULTILINE),
    # Fallback tanpa tree-sitter: tangkap unit & member utama Solidity.
    "solidity": re.compile(
        r"^[ \t]*(?:abstract\s+)?(?:contract|interface|library|struct|enum|event|modifier)\s+(\w+)\b|"
        r"^[ \t]*(constructor)\s*\(|"
        r"^[ \t]*function\s+(\w+)\s*\(",
        re.MULTILINE,
    ),
    "kotlin": re.compile(
        r"^[ \t]*(?:data\s+|enum\s+|sealed\s+|abstract\s+|open\s+)?(?:class|interface|object)\s+(\w+)\b|"
        r"^[ \t]*(?:suspend\s+|private\s+|public\s+|internal\s+|inline\s+|override\s+)*fun\s+(?:[\w.<>?]+\.)?(\w+)\s*\(",
        re.MULTILINE,
    ),
    "swift": re.compile(
        r"^[ \t]*(?:open\s+|public\s+|final\s+|indirect\s+)?(?:class|struct|enum|protocol|extension)\s+(\w+)\b|"
        r"^[ \t]*(?:static\s+|class\s+|mutating\s+|override\s+|public\s+|private\s+|fileprivate\s+)*func\s+(\w+)\s*\(|"
        r"^[ \t]*(?:convenience\s+|override\s+|required\s+)*(init)\s*\(",
        re.MULTILINE,
    ),
    "dart": re.compile(
        r"^[ \t]*(?:abstract\s+|base\s+|sealed\s+)?(?:class|mixin|enum|extension)\s+(\w+)\b|"
        r"^[ \t]*(?:static\s+|external\s+|factory\s+)*(?:[\w<>,?\s]+\s+)?(\w+)\s*\([^;{]*\)\s*(?:async\s*)?\{|"
        r"^[ \t]*(?:void|int|double|num|bool|String|Future<[^>]*>|Stream<[^>]*>|List<[^>]*>|Map<[^>]*>|Set<[^>]*>|dynamic)\s+(\w+)\s*\(",
        re.MULTILINE,
    ),
    "lua": re.compile(
        r"^[ \t]*(?:local\s+)?function\s+([\w.:]+)\s*\(|"
        r"^[ \t]*(?:local\s+)?(\w+)\s*=\s*function\s*\(",
        re.MULTILINE,
    ),
    "scala": re.compile(
        r"^[ \t]*(?:sealed\s+|abstract\s+|final\s+|case\s+)?(?:class|trait|object|enum)\s+(\w+)\b|"
        r"^[ \t]*(?:override\s+|private\s*|protected\s*|final\s+|inline\s+)*def\s+(\w+)\s*[\[(=]|"
        r"^[ \t]*(?:lazy\s+)?(?:val|var)\s+(\w+)\b",
        re.MULTILINE,
    ),
    "elixir": re.compile(
        r"^[ \t]*defmodule\s+([\w.]+)\b|"
        r"^[ \t]*(?:def|defp|defmacro|defmacrop)\s+(\w+[!?]?)",
        re.MULTILINE,
    ),
    "haskell": re.compile(
        r"^data\s+(\w+)\b|^newtype\s+(\w+)\b|^type\s+(\w+)\b|^class\s+(\w+)\b|"
        r"^(\w+)\s*::\s*|"                        # type signature:  name :: ...
        r"^(\w+)[ \t]+[\w'()\[\]]*[ \t]*=|"       # function:        name args =
        r"^(\w+)[ \t]*=[ \t]*\S",                # zero-arg bind:   name = expr
        re.MULTILINE,
    ),
    "r": re.compile(
        r"^[ \t]*(`?[\w.]+`?)\s*(?:<-|=|<<-)\s*function\s*\(",
        re.MULTILINE,
    ),
}


def _iter_source_files(root: str, max_files: int = 2000):
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            ext = os.path.splitext(fn)[1]
            if ext in EXT_LANG:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                yield rel, full, EXT_LANG[ext]
                count += 1
                if count >= max_files:
                    return


def _extract_defs_treesitter(path: str, lang: str, source: bytes):
    try:
        parser = _get_parser(lang)
    except Exception:
        return None  # bahasa tidak didukung grammar terinstall
    try:
        tree = parser.parse(source)
    except Exception:
        return None

    defs = []
    src_text = source.decode("utf-8", errors="replace")
    lines = src_text.split("\n")

    def find_name(node):
        for field in NAME_FIELDS:
            child = node.child_by_field_name(field)
            if child is not None:
                return src_text[child.start_byte:child.end_byte]

        for child in node.children:
            if "identifier" in child.type:
                return src_text[child.start_byte:child.end_byte]
        return None

    def add_def(name, node, typ=None):
        start_line = node.start_point[0]
        sig_line = lines[start_line].strip() if start_line < len(lines) else ""
        defs.append({"name": name, "line": start_line + 1, "type": typ or node.type, "sig": sig_line[:160]})

    def node_text(n):
        return src_text[n.start_byte:n.end_byte]

    # ---- walker generik (bahasa dengan struktur AST standar) ----
    def walk_generic(node):
        if node.type in DEF_NODE_TYPES:
            name = find_name(node)
            if name:
                add_def(name, node)
        for child in node.children:
            walk_generic(child)

    # ---- custom walker: Elixir ----
    # def/defp/defstruct muncul sebagai `call` dengan child pertama identifier
    # `def`/dll. Nama simbol = elemen pertama di dalam `arguments`.
    ELIXIR_DEF_TARGETS = {"def", "defp", "defmacro", "defmacrop", "defmodule",
                          "defprotocol", "defimpl", "defstruct", "defexception"}

    def walk_elixir(node, module_stack=()):
        if node.type == "call" and node.children:
            tgt = node.children[0]
            if tgt.type == "identifier" and node_text(tgt) in ELIXIR_DEF_TARGETS:
                keyword = node_text(tgt)
                args = next((c for c in node.children if c.type == "arguments"), None)
                if args is not None and args.children:
                    first = args.children[0]
                    if first.type == "call" and first.children:
                        # "def foo(a, b)" -> arg pertama = call foo(...)
                        name = node_text(first.children[0])
                    else:
                        # "def foo" / "defmodule Foo.Bar"
                        name = node_text(first)
                    if keyword == "defmodule":
                        if name:
                            add_def(name, node, typ="elixir_defmodule")
                        # track enclosing module untuk defstruct/defexception
                        for child in node.children:
                            walk_elixir(child, module_stack + (name,))
                        return
                    if keyword in ("defstruct", "defexception"):
                        # tak punya nama sendiri — pakai nama enclosing module
                        suffix = " (struct)" if keyword == "defstruct" else " (exception)"
                        name = (module_stack[-1] + suffix) if module_stack else None
                    if name:
                        add_def(name, node, typ="elixir_" + keyword)
        for child in node.children:
            walk_elixir(child, module_stack)

    # ---- custom walker: Haskell ----
    # Haskell AST: nama fungsi ada di child langsung `variable`; nama tipe di
    # child langsung `name`. `function` yang bersarang di dalam `signature` adalah
    # tipe RHS (bukan definisi) — jangan descend setelah match, dan jangan proses
    # `function` tanpa child `match`.
    def walk_haskell(node):
        if node.type == "signature":
            name = next((node_text(c) for c in node.children if c.type == "variable"), None)
            if name:
                add_def(name, node, typ="haskell_signature")
            return
        if node.type in ("function", "bind"):
            # `function` = definisi dengan argumen; `bind` = definisi tanpa argumen
            # (mis. `main = print x`). Keduanya punya child `match`.
            # `function` tanpa `match` adalah tipe RHS di dalam signature — skip.
            if not any(c.type == "match" for c in node.children):
                return
            name = next((node_text(c) for c in node.children if c.type == "variable"), None)
            if name:
                add_def(name, node, typ="haskell_" + node.type)
            return
        if node.type in ("data_type", "type_synomym", "newtype"):
            name = next((node_text(c) for c in node.children if c.type == "name"), None)
            if name:
                add_def(name, node, typ="haskell_" + node.type)
            return
        for child in node.children:
            walk_haskell(child)

    # ---- custom walker: R ----
    # Definisi = assignment dengan RHS `function`:
    #   name <- function(a, b) ...   /   name = function(...)  /  `name` <- function(...)
    def walk_r(node):
        if node.type in ("binary_operator", "equals_assignment"):
            lhs = node.child_by_field_name("lhs") or (node.children[0] if node.children else None)
            rhs = node.child_by_field_name("rhs") or (node.children[-1] if node.children else None)
            if lhs is not None and rhs is not None and rhs.type in ("function_definition", "function"):
                name = node_text(lhs)
                add_def(name, node, typ="r_function")
        for child in node.children:
            walk_r(child)

    # ---- custom walker: Lua ----
    # function foo.bar:baz(...) -> function_declaration/function_definition
    #   dengan nama dot_index_expression / method_index_expression.
    # local function f() -> sudah function_declaration.
    # foo = function() -> assignment_statement dengan variable_list.
    def lua_name_from(node):
        if node.type in ("identifier",):
            return node_text(node)
        if node.type in ("dot_index_expression", "method_index_expression"):
            return node_text(node)
        return None

    def walk_lua(node):
        if node.type in ("function_declaration", "function_definition"):
            name_node = (node.child_by_field_name("name") or
                         next((c for c in node.children
                               if c.type in ("identifier", "dot_index_expression",
                                             "method_index_expression")), None))
            if name_node is not None:
                add_def(node_text(name_node), node, typ="lua_function")
        elif node.type == "assignment_statement":
            # foo = function() ... / local foo = function() ...
            # (assignment_statement bisa berada di dalam variable_declaration)
            expr_list = next((c for c in node.children if c.type == "expression_list"), None)
            has_fn = any(c.type == "function_definition"
                         for c in (expr_list.children if expr_list else node.children))
            if has_fn:
                var_list = next((c for c in node.children if c.type == "variable_list"), None)
                if var_list is not None and var_list.children:
                    add_def(node_text(var_list.children[0]), node, typ="lua_function")
        for child in node.children:
            walk_lua(child)

    walkers = {
        "elixir": walk_elixir,
        "haskell": walk_haskell,
        "r": walk_r,
        "lua": walk_lua,
    }
    walker = walkers.get(lang, walk_generic)
    walker(tree.root_node)
    return defs


def _extract_defs_regex(path: str, lang: str, source_text: str):
    defs = []
    patterns = []
    if lang == "python":
        patterns = [REGEX_DEFS["python"], REGEX_DEFS["python_class"]]
    elif lang in ("javascript", "typescript", "tsx"):
        patterns = [REGEX_DEFS["javascript"]]
    elif lang == "go":
        patterns = [REGEX_DEFS["go"]]
    elif lang == "rust":
        patterns = [REGEX_DEFS["rust"]]
    elif lang == "java":
        patterns = [REGEX_DEFS["java"]]
    elif lang == "solidity":
        patterns = [REGEX_DEFS["solidity"]]
    elif lang in ("kotlin", "swift", "dart", "lua", "scala", "elixir", "haskell", "r"):
        patterns = [REGEX_DEFS[lang]]
    else:
        return defs

    for pat in patterns:
        for m in pat.finditer(source_text):
            name = next((g for g in m.groups() if g), None)
            if not name:
                continue
            line_no = source_text[:m.start()].count("\n") + 1
            defs.append({"name": name, "line": line_no, "type": "def", "sig": m.group(0).strip()[:160]})
    return defs


def extract_defs(full_path: str, lang: str):
    """Ekstrak daftar definisi simbol dari satu file. Mengembalikan list of dict."""
    try:
        with open(full_path, "rb") as f:
            raw = f.read()
    except Exception:
        return []

    if _TS_AVAILABLE:
        result = _extract_defs_treesitter(full_path, lang, raw)
        if result is not None:
            return result

    text = raw.decode("utf-8", errors="replace")
    return _extract_defs_regex(full_path, lang, text)


def outline_for_file(full_path: str, workdir: str, db_path: str = None) -> str:
    """Outline ringkas satu file (dipakai tools.py saat file terlalu besar
    untuk didorong penuh ke context). Pakai cache DB kalau tersedia."""
    ext = os.path.splitext(full_path)[1]
    lang = EXT_LANG.get(ext)
    if lang is None:
        return ""

    try:
        st = os.stat(full_path)
    except OSError:
        return ""

    rel = os.path.relpath(full_path, workdir)

    if db_path:
        cached = dbmod.get_cached_outline(db_path, workdir, rel, st.st_mtime, st.st_size)
        if cached:
            return cached["outline"]

    defs = extract_defs(full_path, lang)
    if not defs:
        outline = "(tidak ada simbol top-level yang terdeteksi -- mungkin file data/config)"
    else:
        lines = [f"  {d['line']:>6}  {d['sig']}" for d in defs]
        outline = "\n".join(lines)

    if db_path:
        dbmod.set_cached_outline(db_path, workdir, rel, st.st_mtime, st.st_size, outline, lang)

    return outline



def _power_iteration_pagerank(nodes, edges, damping=0.85, iters=50):
    """edges: dict[(src, dst)] -> weight. Mengembalikan dict node->skor."""
    n = len(nodes)
    if n == 0:
        return {}
    out_weight = defaultdict(float)
    adj = defaultdict(list)  # dst -> list of (src, weight)

    for (src, dst), w in edges.items():
        if src == dst:
            continue
        out_weight[src] += w
        adj[dst].append((src, w))

    rank = {node: 1.0 / n for node in nodes}
    base = (1.0 - damping) / n

    for _ in range(iters):
        new_rank = {}
        for node in nodes:
            incoming = 0.0
            for src, w in adj.get(node, []):
                if out_weight[src] > 0:
                    incoming += rank[src] * (w / out_weight[src])
            new_rank[node] = base + damping * incoming

        rank = new_rank

    return rank


def build_graph_and_rank(root: str, personalize: set = None, max_files: int = 2000):
    """Kembalikan (file_defs: dict[rel_path]->list[def], ranks: dict[rel_path]->float)."""
    file_defs = {}
    def_owner = {}  # identifier_name -> rel_path pemilik definisi (yang paling awal ditemukan)
    file_text = {}

    for rel, full, lang in _iter_source_files(root, max_files=max_files):
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            continue
        file_text[rel] = text
        defs = extract_defs(full, lang)
        file_defs[rel] = defs
        for d in defs:
            name = d["name"]
            if len(name) >= 3 and name not in def_owner:
                def_owner[name] = rel

    nodes = list(file_defs.keys())
    edges = defaultdict(float)

    for rel, text in file_text.items():
        for name, owner in def_owner.items():
            if owner == rel:
                continue

            if re.search(r"\b" + re.escape(name) + r"\b", text):
                weight = 10.0 if (personalize and rel in personalize) else 1.0
                edges[(rel, owner)] += weight

    ranks = _power_iteration_pagerank(nodes, edges)
    return file_defs, ranks


def generate(root: str, token_budget: int = 1024, personalize_files=None, max_files: int = 2000) -> str:
    """Hasilkan repo map dalam bentuk teks, dibatasi token_budget (estimasi kasar
    4 char/token). personalize_files: set path relatif file yang lagi 'hangat'
    (baru dibaca/diedit) supaya diberi bobot lebih di ranking."""
    personalize = set(personalize_files or [])
    file_defs, ranks = build_graph_and_rank(root, personalize=personalize, max_files=max_files)

    if not file_defs:
        return "(tidak ditemukan file source yang dikenali di direktori ini)"

    ranked_files = sorted(file_defs.keys(), key=lambda f: ranks.get(f, 0.0), reverse=True)

    budget_chars = token_budget * 4
    out_lines = []
    used_chars = 0
    engine = "tree-sitter" if _TS_AVAILABLE else "regex-fallback"
    header = f"# Repo map ({engine}, top file oleh relevansi/PageRank, budget ~{token_budget} token)\n"
    used_chars += len(header)
    out_lines.append(header)

    for rel in ranked_files:
        defs = file_defs[rel]
        if not defs:
            continue

        block_lines = [f"{rel}:"]
        for d in defs[:8]:
            block_lines.append(f"    {d['sig']}")
        block = "\n".join(block_lines) + "\n"

        if used_chars + len(block) > budget_chars and out_lines:
            break
        out_lines.append(block)
        used_chars += len(block)

    return "\n".join(out_lines).strip()