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
import threading
import time
from collections import defaultdict

from . import db as dbmod


_TS_AVAILABLE = False
_get_parser = None

# ---------------------------------------------------------------------------
# Loader tree-sitter multi-tier (poor-man's LSP, tanpa LSP/daemon).
#
# Urutan prioritas grammar:
#   1. tree-sitter-language-pack  -> get_parser(lang) (primary, multi-bahasa)
#   2. grammar individual          -> tree_sitter.<lang> (per-bahasa, di-build
#      dari source; andal di Termux/Android di mana language-pack .abi3.so
#      sering gagal dimuat atau panic rustls-platform-verifier)
#   3. tree_sitter_languages       -> get_parser(lang) (fallback lama)
#
# `_get_parser(lang)` SELALU mengembalikan objek dengan method `.parse(bytes)`
# yang mengembalikan Tree, ATAU None kalau bahasa tak didukung. Panic Rust
# (pyo3 PanicException, BaseException) ditangkap di pemanggil supaya garwa
# tidak pernah crash — cukup fallback ke regex.
# ---------------------------------------------------------------------------

try:
    from tree_sitter_language_pack import get_parser as _lp_get_parser  # type: ignore
except Exception:
    _lp_get_parser = None

try:
    from tree_sitter_languages import get_parser as _tl_get_parser  # type: ignore
except Exception:
    _tl_get_parser = None

# Grammar individual: nama modul python per bahasa (opsional, di-build dari
# source). Dipakai bila language-pack tak tersedia / panic.
_INDIVIDUAL_GRAMMARS = {
    "python": "tree_sitter_python",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "c": "tree_sitter_c",
    "cpp": "tree_sitter_cpp",
    "java": "tree_sitter_java",
    "go": "tree_sitter_go",
    "rust": "tree_sitter_rust",
    "c_sharp": "tree_sitter_c_sharp",
    "ruby": "tree_sitter_ruby",
    "php": "tree_sitter_php",
    "swift": "tree_sitter_swift",
    "kotlin": "tree_sitter_kotlin",
    "bash": "tree_sitter_bash",
    "html": "tree_sitter_html",
    "css": "tree_sitter_css",
    "json": "tree_sitter_json",
    "yaml": "tree_sitter_yaml",
    "markdown": "tree_sitter_markdown",
    "toml": "tree_sitter_toml",
}
# cache: lang -> parser (atau None kalau tak didukung).
# PENTING: disimpan di thread-local storage (bukan dict global) karena objek
# Parser tree-sitter TIDAK thread-safe untuk parse bersamaan. Sub-agent paralel
# (spawn_agents_parallel) memakai thread pool, jadi kalau parser dibagi global,
# dua thread bisa memanggil .parse() pada objek yang sama bersamaan -> crash/
# panic. Dengan thread-local, tiap thread punya parser sendiri yang aman.
_individual_parser_cache: "threading.local" = threading.local()


def _individual_parser(lang: str):
    """Buat parser dari grammar individual untuk `lang`, atau None.

    Cache per-thread (thread-local) supaya parser tidak dibagi lintas thread
    (objek Parser tree-sitter tidak thread-safe untuk parse bersamaan).
    """
    cache = _individual_parser_cache.__dict__
    if lang in cache:
        return cache[lang]
    mod_name = _INDIVIDUAL_GRAMMARS.get(lang)
    parser = None
    if mod_name:
        try:
            import importlib
            mod = importlib.import_module(mod_name)
            from tree_sitter import Language, Parser
            # Beberapa grammar menamai fungsi bahasa berbeda:
            #   - umum:          language()
            #   - typescript:    language_typescript() / language_tsx()
            #   - c_sharp:       language_c_sharp()
            #   - php:           language_php()
            # Coba beberapa nama sampai dapat objek Language/PyCapsule.
            lang_obj = None
            for fn_name in ("language", f"language_{lang}", "language_tsx", "language_ts"):
                fn = getattr(mod, fn_name, None)
                if fn is None:
                    continue
                try:
                    lang_obj = fn()
                    if lang_obj is not None:
                        break
                except BaseException:  # noqa: BLE001
                    continue
            if lang_obj is None:
                parser = None
                return
            if not isinstance(lang_obj, Language):
                # tree-sitter-python 0.25 dkk mengembalikan PyCapsule; bungkus.
                lang_obj = Language(lang_obj)
            p = Parser(lang_obj)
            parser = p
        except BaseException:  # noqa: BLE001 — grammar tak terinstall/rubah API
            parser = None
    cache[lang] = parser
    return parser


_get_parser_cache: "threading.local" = threading.local()


def _get_parser(lang: str):
    """Kembalikan parser untuk `lang` (objek dengan .parse(bytes) -> Tree),
    atau None bila tak tersedia. Prioritas: language-pack -> individual ->
    tree_sitter_languages.

    Hasil di-cache per-thread (thread-local) supaya objek Parser yang sama
    tidak dipakai parse bersamaan oleh beberapa thread sub-agent paralel
    (Parser tree-sitter tidak thread-safe). Tiap thread mendapat parser
    sendiri yang aman.
    """
    cache = _get_parser_cache.__dict__
    if lang in cache:
        return cache[lang]
    parser = None
    # 1. language-pack (primary)
    if _lp_get_parser is not None:
        try:
            parser = _lp_get_parser(lang)
        except BaseException:  # noqa: BLE001 — panic Rust / import gagal
            parser = None
    # 2. grammar individual (andal di Termux/Android)
    if parser is None:
        parser = _individual_parser(lang)
    # 3. tree_sitter_languages (fallback lama)
    if parser is None and _tl_get_parser is not None:
        try:
            parser = _tl_get_parser(lang)
        except BaseException:  # noqa: BLE001
            parser = None
    cache[lang] = parser
    return parser


def _ts_available() -> bool:
    """True kalau tree-sitter core tersedia (untuk grammar individual) ATAU
    language-pack / tree_sitter_languages terinstall. Grammar individual
    butuh modul `tree_sitter` (core) yang menyediakan Parser + Language."""
    try:
        import tree_sitter  # noqa: F401
        core_ok = True
    except Exception:
        core_ok = False
    return _lp_get_parser is not None or _tl_get_parser is not None or core_ok


_TS_AVAILABLE = _ts_available()

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


# File yang selalu penting untuk disertakan dalam repo map (mirip Aider's
# filter_important_files): dokumen, build config, dsb.
_IMPORTANT_FILENAMES = {
    "readme.md", "readme", "readme.txt", "readme.rst",
    "makefile", "cmakelists.txt", "dockerfile", "docker-compose.yml",
    "docker-compose.yaml", "license", "license.md", "license.txt",
    "contributing.md", "changelog.md", "changelog", "go.mod", "go.sum",
    "package.json", "pyproject.toml", "setup.py", "setup.cfg",
    "requirements.txt", "cargo.toml", "pom.xml", "build.gradle",
    "build.gradle.kts", "gemfile", "gemfile.lock", "pipeline.yml",
    "azure-pipelines.yml", ".gitignore", "tsconfig.json", "webpack.config.js",
    "vite.config.js", "vite.config.ts", "jest.config.js", "eslint.config.js",
    "vitest.config.ts", "tsconfig.json",
}


def _filter_important_files(rel_fnames) -> list:
    """Kembalikan file penting (README/Makefile/LICENSE/dll) yang ada di repo.

    File penting selalu disertakan dalam repo map walau rank PageRank-nya
    rendah, karena memberi konteks proyek (dokumentasi, build config).
    """
    important = []
    for rel in rel_fnames:
        base = os.path.basename(rel).lower()
        if base in _IMPORTANT_FILENAMES or rel.lower() in _IMPORTANT_FILENAMES:
            important.append(rel)
    return important


def _preview_text(root: str, rel: str, max_lines: int = 6, max_chars: int = 120) -> list:
    """Ambil preview baris-baris pertama file (untuk file penting tanpa simbol)."""
    try:
        full = os.path.join(root, rel)
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            lines = []
            for i, ln in enumerate(f):
                if i >= max_lines:
                    break
                ln = ln.rstrip("\n")[:max_chars]
                if ln.strip():
                    lines.append(ln)
            return lines
    except Exception:
        return []


def _iter_source_files(root: str, max_files: int = 2000,
                       time_budget: float = 10.0, byte_budget: int = 64 * 1024 * 1024):
    """Iterasi file source di repo, dengan guard agar tidak hang/gembung di
    repo besar. Berhenti lebih awal bila:
      - sudah melewati `max_files`, ATAU
      - total ukuran file yang dihasilkan melebihi `byte_budget`, ATAU
      - sudah berjalan lebih dari `time_budget` detik.
    Return (generator) yield (rel, full, lang)."""
    count = 0
    total_bytes = 0
    start = time.monotonic()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            # Guard max_files dicek di AWAL loop (sebelum yield) supaya
            # max_files=0 benar-benar tidak menghasilkan file apa pun.
            if count >= max_files:
                return
            if time.monotonic() - start > time_budget:
                return
            ext = os.path.splitext(fn)[1]
            base_lower = fn.lower()
            if ext in EXT_LANG:
                full = os.path.join(dirpath, fn)
                try:
                    total_bytes += os.path.getsize(full)
                except OSError:
                    pass
                if total_bytes > byte_budget:
                    return
                rel = os.path.relpath(full, root)
                count += 1
                yield rel, full, EXT_LANG[ext]
            elif base_lower in _IMPORTANT_FILENAMES:
                # File penting (README/Makefile/LICENSE/dll) ikut dihasilkan
                # walau tanpa ekstensi bahasa, supaya P3 (filter_important_files)
                # benar-benar bisa memasukkannya ke map.
                full = os.path.join(dirpath, fn)
                try:
                    total_bytes += os.path.getsize(full)
                except OSError:
                    pass
                if total_bytes > byte_budget:
                    return
                rel = os.path.relpath(full, root)
                count += 1
                yield rel, full, None


def _extract_defs_treesitter(path: str, lang: str, source: bytes):
    try:
        # BaseException: pyo3 PanicException (panic Rust) bukan Exception.
        parser = _get_parser(lang)
    except BaseException:
        return None  # bahasa tidak didukung grammar terinstall
    try:
        tree = parser.parse(source)
    except BaseException:
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


def _collect_identifiers_treesitter(path: str, lang: str, source: bytes):
    """Kumpulkan semua nama identifier yang muncul di AST (referensi potensial).

    Lebih akurat daripada regex `\\bname\\b` scan karena tidak menangkap nama
    yang kebetulan muncul di dalam string literal / komentar. Mengembalikan
    set nama, atau None kalau grammar tak tersedia (pemanggil fallback regex).
    """
    if not lang:
        return set()  # file penting tanpa bahasa: tidak ada identifier AST
    try:
        parser = _get_parser(lang)
    except BaseException:
        return None
    try:
        tree = parser.parse(source)
    except BaseException:
        return None
    src_text = source.decode("utf-8", errors="replace")
    idents = set()

    def _walk(node):
        if "identifier" in node.type:
            txt = src_text[node.start_byte:node.end_byte]
            if txt and txt.isidentifier():
                idents.add(txt)
        for child in node.children:
            _walk(child)

    _walk(tree.root_node)
    return idents


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
    if not lang:
        # File penting (README/Makefile/LICENSE/dll) tanpa bahasa: tidak punya
        # definisi simbol, tapi tetap bisa masuk map sebagai file berkonteks.
        return []
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


# ---------------------------------------------------------------------------
# Snippet konteks AST (poor-man's LSP) — dipakai tool 'snippet' & 'check'
# ---------------------------------------------------------------------------

def snippet_for_position(full_path: str, line: int, radius: int = 5) -> str:
    """Ambil snippet konteks di sekitar posisi `line` (1-based) pada file.

    Dengan tree-sitter (kalau tersedia): cari node AST terkecil yang memuat
    posisi tsb via named_descendant_for_point_range, lalu naik ke node pemilik
    terluar yang masih masuk akal (fungsi/class/metode, maks ~60 baris),
    ekstrak nama simbol pemilik, render 5-15 baris konteks + header.
    Fallback (tanpa tree-sitter / grammar tak tersedia): render baris
    [line-radius, line+radius] polos.

    Tidak pernah melempar exception — selalu kembalikan string ber-format.
    """
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except Exception as e:  # noqa: BLE001
        return f"[snippet] Gagal membaca {full_path}: {e}"
    if not lines:
        return "[snippet] (file kosong)"
    try:
        line = max(1, int(line))
    except (TypeError, ValueError):
        line = 1

    if _TS_AVAILABLE:
        s = _snippet_via_treesitter(full_path, lines, line, radius)
        if s:
            return s

    # Fallback regex/baris: ambil baris sekitar posisi.
    lo = max(0, line - 1 - radius)
    hi = min(len(lines), line - 1 + radius + 1)
    ctx = "\n".join(f"{i + 1:6d}\t{lines[i]}" for i in range(lo, hi))
    return f"[snippet] {os.path.basename(full_path)} (fallback, sekitar baris {line}):\n{ctx}"


# ---------------------------------------------------------------------------
# Cache tree-sitter + incremental parse (P3)
# ---------------------------------------------------------------------------
# Simpan Tree hasil parse per (path, hash konten) supaya edit berikutnya bisa
# re-parse HANYA bagian yang berubah via tree.edit() + parser.parse(new_src,
# old_tree) — jauh lebih cepat daripada parse penuh untuk file besar di loop
# auto-check pasca-edit. Cache dibatasi ukurannya (LRU sederhana).
_ts_tree_cache: dict = {}          # path -> (content_hash, src_bytes, Tree)
_ts_tree_cache_order: list = []    # path, urutan akses untuk LRU
_TS_TREE_CACHE_MAX = 64


def _tree_edit(tree, old_src: bytes, new_src: bytes) -> None:
    """Terapkan perbedaan byte old->new ke tree lama (incremental).

    py-tree-sitter 0.25+ menyediakan Tree.edit(start_byte, old_end_byte,
    new_end_byte). Mari kita hitung titik beda pertama & terakhir dari dua
    buffer, lalu panggil tree.edit. Kalau API tak tersedia (versi lama),
    kita diamkan (parse penuh akan dipakai sebagai fallback).
    """
    # cari posisi byte pertama yang berbeda
    n = min(len(old_src), len(new_src))
    start = 0
    while start < n and old_src[start] == new_src[start]:
        start += 1
    # cari posisi byte terakhir yang berbeda (dari belakang)
    old_end = len(old_src)
    new_end = len(new_src)
    while (old_end > start and new_end > start
           and old_src[old_end - 1] == new_src[new_end - 1]):
        old_end -= 1
        new_end -= 1
    if start == old_end and start == new_end:
        return  # tidak ada perubahan
    edit = getattr(tree, "edit", None)
    if edit is None:
        return
    try:
        edit(start, old_end, new_end)
    except Exception:
        pass


def parse_with_cache(full_path: str, lang: str) -> tuple:
    """Parse file dengan tree-sitter, pakai incremental bila ada cache.

    Mengembalikan (tree, src_bytes, src_text). Kalau tree-sitter tidak
    tersedia / grammar tak ada, mengembalikan (None, None, None).
    """
    if not _TS_AVAILABLE:
        return None, None, None
    try:
        # Catatan: pyo3 PanicException (panic Rust, mis. rustls-platform-verifier
        # di Termux/Android) adalah BaseException, BUKAN Exception — jadi kita
        # tangkap BaseException agar get_parser yang panic tidak crash garwa.
        parser = _get_parser(lang)
    except BaseException:
        return None, None, None
    try:
        with open(full_path, "rb") as f:
            src = f.read()
    except Exception:
        return None, None, None

    import hashlib
    h = hashlib.sha256(src).hexdigest()
    cached = _ts_tree_cache.get(full_path)
    if cached and cached[0] == h:
        # konten sama persis -> pakai tree lama (tidak perlu parse ulang)
        return cached[2], src, src.decode("utf-8", errors="replace")

    try:
        if cached:
            # konten berubah -> incremental parse: edit tree lama agar bisa
            # dipakai sebagai hint oleh parser.parse(new_src, old_tree).
            _tree_edit(cached[2], cached[1], src)
            tree = parser.parse(src, cached[2])
        else:
            tree = parser.parse(src)
    except BaseException:
        try:
            tree = parser.parse(src)  # fallback parse penuh
        except BaseException:
            return None, None, None  # tree-sitter rusak -> fallback regex

    # simpan cache (LRU sederhana)
    _ts_tree_cache[full_path] = (h, src, tree)
    if full_path in _ts_tree_cache_order:
        _ts_tree_cache_order.remove(full_path)
    _ts_tree_cache_order.append(full_path)
    while len(_ts_tree_cache_order) > _TS_TREE_CACHE_MAX:
        evict = _ts_tree_cache_order.pop(0)
        _ts_tree_cache.pop(evict, None)

    return tree, src, src.decode("utf-8", errors="replace")


def invalidate_tree_cache(full_path: str) -> None:
    """Buang cache tree-sitter untuk satu path (dipanggil setelah write/edit)."""
    _ts_tree_cache.pop(full_path, None)
    if full_path in _ts_tree_cache_order:
        _ts_tree_cache_order.remove(full_path)


def _node_name(node, src_text: str) -> str:
    """Ekstrak nama simbol dari node AST (field name/identifier/declarator)."""
    for field in NAME_FIELDS:
        child = node.child_by_field_name(field)
        if child is not None:
            return src_text[child.start_byte:child.end_byte]
    for child in node.named_children:
        if child.type in ("identifier", "name", "field_identifier", "type_identifier"):
            return src_text[child.start_byte:child.end_byte]
    return ""


def _snippet_via_treesitter(full_path: str, lines: list, line: int, radius: int) -> str:
    """Snippet berbasis AST pakai tree-sitter. '' kalau gagal/tak tersedia."""
    try:
        ext = os.path.splitext(full_path)[1]
        lang = EXT_LANG.get(ext)
        if not lang:
            return ""
        tree, _src, src_text = parse_with_cache(full_path, lang)
        if tree is None:
            return ""
        root = tree.root_node

        row = line - 1
        col_hi = max(len(lines[row]) if 0 <= row < len(lines) else 0, 1)
        node = root.named_descendant_for_point_range((row, 0), (row, col_hi))
        if node is None:
            return ""

        # Naik ke node pemilik terluar yang masih masuk akal (fungsi/class/def).
        owner = node
        while (owner.parent is not None
               and owner.parent.start_point[0] <= row <= owner.parent.end_point[0]
               and (owner.parent.end_point[0] - owner.parent.start_point[0]) <= 60):
            owner = owner.parent
            if owner.parent is None or owner.type in ("module", "translation_unit", "program", "source_file"):
                break

        start_r = max(0, owner.start_point[0])
        end_r = min(len(lines) - 1, owner.end_point[0])
        if end_r - start_r > 15:
            # owner terlalu panjang (file/modul) -> batasi ke sekitar error
            start_r = max(0, row - radius)
            end_r = min(len(lines) - 1, row + radius)

        ctx = "\n".join(f"{i + 1:6d}\t{lines[i]}" for i in range(start_r, end_r + 1))
        name = _node_name(owner, src_text)
        name_part = f" '{name}'" if name else ""
        return (f"[snippet] {os.path.basename(full_path)} — {owner.type}{name_part} "
                f"(baris {start_r + 1}-{end_r + 1}):\n{ctx}")
    except Exception:  # noqa: BLE001
        return ""


def _power_iteration_pagerank(nodes, edges, damping=0.85, iters=50,
                              personalization=None, dangling=None):
    """Power-iteration PageRank. edges: dict[(src, dst)] -> weight.

    personalization: dict node->bobot personalisasi (default 1/n per node,
    seperti nx.pagerank). dangling: dict node->distribusi untuk node tanpa
    out-edge (default = personalization). Mengembalikan dict node->skor.
    """
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

    # Personalization: default 1/n per node (konsisten nx.pagerank).
    if personalization:
        pers_sum = sum(personalization.values())
        if pers_sum <= 0:
            pers = {node: 1.0 / n for node in nodes}
        else:
            pers = {node: personalization.get(node, 0.0) / pers_sum for node in nodes}
    else:
        pers = {node: 1.0 / n for node in nodes}

    # Dangling: node tanpa out-edge mendistribusikan rank ke pers (default).
    if dangling is None:
        dangling = pers

    rank = {node: 1.0 / n for node in nodes}
    base = (1.0 - damping)

    # Precompute dangling sum (total rank node tanpa out-edge).
    dangling_nodes = [node for node in nodes if out_weight[node] <= 0]

    for _ in range(iters):
        new_rank = {}
        dangling_sum = sum(rank[node] for node in dangling_nodes)
        for node in nodes:
            incoming = 0.0
            for src, w in adj.get(node, []):
                if out_weight[src] > 0:
                    incoming += rank[src] * (w / out_weight[src])
            # Personalization teleport + dangling redistribution.
            new_rank[node] = (base * pers[node]) + damping * (
                incoming + dangling_sum * dangling.get(node, 0.0)
            )
        rank = new_rank

    return rank


def build_graph_and_rank(root: str, personalize: set = None, max_files: int = 2000):
    """Kembalikan (file_defs, file_refs, ranked_definitions, ranks).

    - file_defs: dict[rel_path] -> list[def]
    - file_refs: dict[rel_path] -> set[nama identifier yang dirujuk]
    - ranked_definitions: list[(rel_path, ident, rank_skor)] terurut menurun
    - ranks: dict[rel_path] -> float (skor PageRank file)

    Graph dibangun dari references AST (bukan regex \\bname\\b scan) sehingga
    lebih akurat: nama yang kebetulan muncul di string/komentar tidak dihitung.
    Personalization memberi bobot ekstra pada file yang sedang 'hangat'
    (baru dibaca/diedit) dan pada file yang dirujuk dari file hangat.
    """
    file_defs = {}
    file_refs = {}
    def_owner = {}  # identifier_name -> rel_path pemilik definisi (yang paling awal)
    file_text = {}

    for rel, full, lang in _iter_source_files(root, max_files=max_files):
        try:
            with open(full, "rb") as f:
                raw = f.read()
        except Exception:
            continue
        file_text[rel] = raw
        defs = extract_defs(full, lang)
        file_defs[rel] = defs
        for d in defs:
            name = d["name"]
            if len(name) >= 3 and name not in def_owner:
                def_owner[name] = rel

        # References via AST (lebih akurat), fallback ke identifier regex scan.
        refs = _collect_identifiers_treesitter(full, lang, raw)
        if refs is None:
            text = raw.decode("utf-8", errors="replace")
            refs = set(re.findall(r"\b[A-Za-z_]\w{2,}\b", text))
        file_refs[rel] = refs

    nodes = list(file_defs.keys())
    edges = defaultdict(float)

    # Bobot multiplier untuk identifier (mirip Aider): snake/kebab/camel case
    # panjang lebih informatif; underscore-prefix (private) diturunkan.
    def _ident_mul(name: str) -> float:
        mul = 1.0
        is_snake = ("_" in name) and any(c.isalpha() for c in name)
        is_kebab = ("-" in name) and any(c.isalpha() for c in name)
        is_camel = any(c.isupper() for c in name) and any(c.islower() for c in name)
        if (is_snake or is_kebab or is_camel) and len(name) >= 8:
            mul *= 10
        if name.startswith("_"):
            mul *= 0.1
        return mul

    for rel, refs in file_refs.items():
        for name in refs:
            owner = def_owner.get(name)
            if owner is None or owner == rel:
                continue
            # Bobot: multiplier identitas + personalization + sqrt frekuensi.
            mul = _ident_mul(name)
            if personalize and rel in personalize:
                mul *= 10.0
            edges[(rel, owner)] += mul

    # Personalization: file hangat + file yang dirujuk dari file hangat.
    personalization = {}
    if personalize:
        for rel in nodes:
            if rel in personalize:
                personalization[rel] = personalization.get(rel, 0.0) + 100.0
        # File yang dirujuk dari file hangat ikut naik.
        for rel in personalize:
            for name in file_refs.get(rel, set()):
                owner = def_owner.get(name)
                if owner and owner != rel:
                    personalization[owner] = personalization.get(owner, 0.0) + 10.0

    ranks = _power_iteration_pagerank(
        nodes, edges, personalization=personalization or None
    )

    # Distribusi rank ke definisi (mirip Aider): dari tiap node, sebarkan rank
    # ke out-edges sesuai proporsi bobot. ranked_definitions = list[(dst, ident, skor)].
    ranked_definitions = defaultdict(float)
    for (src, dst), w in edges.items():
        total_out = sum(
            ww for (ss, dd), ww in edges.items() if ss == src
        )
        if total_out <= 0:
            continue
        src_rank = ranks.get(src, 0.0)
        ident = next(
            (name for name, owner in def_owner.items()
             if owner == dst and name in file_refs.get(src, set())),
            None,
        )
        if ident is None:
            continue
        ranked_definitions[(dst, ident)] += src_rank * w / total_out

    ranked_definitions = sorted(
        ranked_definitions.items(), reverse=True, key=lambda x: (x[1], x[0])
    )
    # Bentuk list[(rel, ident, skor)]
    ranked_definitions = [(rel, ident, skor) for (rel, ident), skor in ranked_definitions]

    return file_defs, file_refs, ranked_definitions, ranks


def generate(root: str, token_budget: int = 1024, personalize_files=None, max_files: int = 2000) -> str:
    """Hasilkan repo map dalam bentuk teks, dibatasi token_budget (estimasi kasar
    4 char/token). personalize_files: set path relatif file yang lagi 'hangat'
    (baru dibaca/diedit) supaya diberi bobot lebih di ranking.

    Mengikuti pendekatan Aider: (1) graph references -> PageRank dengan
    personalization; (2) distribusi rank ke definisi; (3) binary search untuk
    menemukan jumlah definisi optimal yang muat dalam budget; (4) file penting
    (README/Makefile/LICENSE/dll) selalu disertakan.
    """
    personalize = set(personalize_files or [])
    file_defs, file_refs, ranked_definitions, ranks = build_graph_and_rank(
        root, personalize=personalize, max_files=max_files
    )

    if not file_defs:
        return "(tidak ditemukan file source yang dikenali di direktori ini)"

    engine = "tree-sitter" if _TS_AVAILABLE else "regex-fallback"
    header = f"# Repo map ({engine}, top simbol oleh relevansi/PageRank, budget ~{token_budget} token)\n"

    # File penting selalu disertakan (P3): README/Makefile/LICENSE/dll.
    important = _filter_important_files(list(file_defs.keys()))

    # Bangun daftar definisi terurut berdasarkan skor rank (definisi dulu,
    # lalu file tanpa definisi, lalu file penting yang belum masuk).
    ordered = []
    seen = set()
    for rel, ident, skor in ranked_definitions:
        key = (rel, ident)
        if key in seen:
            continue
        seen.add(key)
        ordered.append((rel, ident, float(skor)))

    # File yang dirujuk tapi tak punya definisi ter-ranking -> tambahkan file-nya.
    ranked_file_set = {rel for rel, _, _ in ordered}
    for rel in sorted(file_defs.keys(), key=lambda f: ranks.get(f, 0.0), reverse=True):
        if rel not in ranked_file_set and rel not in seen:
            seen.add((rel, None))
            ordered.append((rel, None, float(ranks.get(rel, 0.0))))

    # File penting yang belum masuk -> tambahkan di akhir (selalu disertakan).
    for rel in important:
        if (rel, None) not in seen and rel not in {r for r, _, _ in ordered}:
            seen.add((rel, None))
            ordered.append((rel, None, 1e9))  # skor besar -> pasti masuk

    budget_chars = token_budget * 4

    def _render(ordered_subset):
        """Render daftar (rel, ident, skor) menjadi teks map. Kembalikan (teks, char_count)."""
        out_lines = [header]
        used_chars = len(header)
        file_blocks = {}
        order = []
        for rel, ident, _skor in ordered_subset:
            if rel not in file_blocks:
                file_blocks[rel] = []
                order.append(rel)
            file_blocks[rel].append(ident)
        for rel in order:
            defs = file_defs.get(rel, [])
            block_lines = [f"{rel}:"]
            idents = [i for i in file_blocks[rel] if i is not None]
            if idents:
                # Tampilkan signature dari definisi yang ter-ranking.
                by_name = {d["name"]: d for d in defs}
                for ident in idents:
                    d = by_name.get(ident)
                    if d:
                        block_lines.append(f"    {d['sig']}")
            else:
                # File tanpa definisi ter-ranking: tampilkan beberapa defs pertama.
                for d in defs[:8]:
                    block_lines.append(f"    {d['sig']}")
                if not defs:
                    # File penting tanpa simbol (README/LICENSE/dll): tampilkan
                    # preview baris pertama yang informatif (P4).
                    preview = _preview_text(root, rel)
                    if preview:
                        block_lines.extend(f"    {ln}" for ln in preview)
            block = "\n".join(block_lines) + "\n"
            if used_chars + len(block) > budget_chars and out_lines:
                break
            out_lines.append(block)
            used_chars += len(block)
        return "\n".join(out_lines).strip(), used_chars

    # Binary search (P2a): cari jumlah definisi terbaik yang muat dalam budget.
    # Karena ordered sudah diurutkan menurun oleh rank, binary search pada
    # jumlah item yang diambil.
    lo, hi = 0, len(ordered)
    best_text = ""
    best_chars = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        text, used = _render(ordered[:mid])
        if used <= budget_chars:
            if used > best_chars:
                best_text = text
                best_chars = used
            lo = mid + 1
        else:
            hi = mid - 1

    if not best_text:
        # Bahkan header saja melebihi budget? Kembalikan header minimal.
        return header.strip()
    return best_text