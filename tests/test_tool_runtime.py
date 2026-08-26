"""
test_tool_runtime.py
Uji lapisan eksekusi tool (garwa/tool_runtime/).

Fokus:
- errors: ToolRuntimeError (validasi kind, suggestions, format_for_model),
  tool_error, is_blocked_member, InvalidDataValueError.
- hooks: ToolCallStarted/Ended (slots), ToolCallHooks non-throwing.
- copy_utils: copy_in (validasi data plain, kedalaman, circular, blocked member,
  non-string key, non-plain tipe).
- registry: ToolRegistry (namespace, resolve, search, pagination, signature).
- introspection: parse_argument_description, build_openai_tools_payload.
- executor: run_tool_with_runtime (sukses, TypeError, ToolRuntimeError, generic
  exception, hooks terpanggil, copy_in gagal).
"""

import pytest

from garwa.tool_runtime import _shared as shared
from garwa.tool_runtime.copy_utils import copy_in
from garwa.tool_runtime.errors import (
    InvalidDataValueError,
    ToolRuntimeError,
    is_blocked_member,
    tool_error,
)
from garwa.tool_runtime.executor import run_tool_with_runtime
from garwa.tool_runtime.hooks import (
    DEFAULT_HOOKS,
    ToolCallEnded,
    ToolCallHooks,
    ToolCallStarted,
)
from garwa.tool_runtime.introspection import (
    _coerce_default,
    build_openai_tools_payload,
    parse_argument_description,
)
from garwa.tool_runtime.registry import REGISTRY, ToolRegistry, register_signature
from garwa.tools import _state as shared_state
from garwa.tools.web_search import _resolve_news_locale, _search_google_news_rss, tool_web_search


# ================================================================ errors

def test_tool_runtime_error_valid_kind():
    err = ToolRuntimeError(shared.KIND_UNKNOWN_TOOL, "pesan", ["saran1"])
    assert err.kind == shared.KIND_UNKNOWN_TOOL
    assert err.suggestions == ["saran1"]


def test_tool_runtime_error_invalid_kind_raises():
    with pytest.raises(ValueError):
        ToolRuntimeError("BukanKindValid", "pesan")


def test_tool_runtime_error_default_suggestions():
    err = ToolRuntimeError(shared.KIND_INVALID_TOOL_INPUT, "pesan")
    assert err.suggestions == []


def test_format_for_model_with_suggestions():
    err = tool_error(shared.KIND_INVALID_TOOL_INPUT, "input salah", ["cek a", "cek b"])
    out = err.format_for_model()
    assert out.startswith("[ERROR] InvalidToolInput: input salah")
    assert "Saran:" in out
    assert "1. cek a" in out
    assert "2. cek b" in out


def test_format_for_model_without_suggestions():
    err = tool_error(shared.KIND_INVALID_TOOL_OUTPUT, "output rusak")
    out = err.format_for_model()
    assert out == "[ERROR] InvalidToolOutput: output rusak"


def test_tool_error_returns_runtime_error():
    err = tool_error(shared.KIND_UNKNOWN_TOOL, "m")
    assert isinstance(err, ToolRuntimeError)


def test_is_blocked_member():
    assert is_blocked_member("__proto__")
    assert is_blocked_member("constructor")
    assert is_blocked_member("prototype")
    assert not is_blocked_member("normal_key")


def test_invalid_data_value_error_kind():
    err = InvalidDataValueError("nilai buruk")
    assert err.kind == shared.KIND_INVALID_DATA_VALUE
    assert isinstance(err, ToolRuntimeError)


# ================================================================ hooks

def test_tool_call_started_slots():
    c = ToolCallStarted(0, "read_file", {"path": "x"})
    assert c.index == 0
    assert c.name == "read_file"
    assert c.input == {"path": "x"}


def test_tool_call_ended_slots():
    c = ToolCallEnded(0, "read_file", {}, 5.0, "success")
    assert c.outcome == "success"
    assert c.message is None
    c2 = ToolCallEnded(0, "read_file", {}, 5.0, "failure", "err")
    assert c2.message == "err"


def test_hooks_fire_start_and_end():
    events = []
    hooks = ToolCallHooks(
        on_tool_call_start=lambda c: events.append(("start", c.name)),
        on_tool_call_end=lambda c: events.append(("end", c.outcome)),
    )
    hooks.fire_start(ToolCallStarted(0, "ls", {}))
    hooks.fire_end(ToolCallEnded(0, "ls", {}, 1.0, "success"))
    assert events == [("start", "ls"), ("end", "success")]


def test_hooks_swallow_exceptions():
    def bad_start(c):
        raise RuntimeError("hook rusak")

    hooks = ToolCallHooks(on_tool_call_start=bad_start)
    # Tidak boleh melempar walau hook error.
    hooks.fire_start(ToolCallStarted(0, "x", {}))


def test_hooks_none_callbacks_noop():
    hooks = ToolCallHooks()
    hooks.fire_start(ToolCallStarted(0, "x", {}))
    hooks.fire_end(ToolCallEnded(0, "x", {}, 1.0, "success"))


def test_default_hooks_is_instance():
    assert isinstance(DEFAULT_HOOKS, ToolCallHooks)


# ================================================================ copy_utils

def test_copy_in_leaf_types():
    assert copy_in("str") == "str"
    assert copy_in(42) == 42
    assert copy_in(True) is True
    assert copy_in(None) is None


def test_copy_in_deep_copies():
    src = {"a": [1, 2, {"b": 3}]}
    out = copy_in(src)
    assert out == src
    assert out is not src
    assert out["a"] is not src["a"]


def test_copy_in_returns_new_dict_list():
    src = {"k": [1, 2]}
    out = copy_in(src)
    out["k"].append(99)
    assert src["k"] == [1, 2]  # asli tidak termutasi


def test_copy_in_accepts_tuple():
    assert copy_in((1, 2)) == [1, 2]


def test_copy_in_rejects_non_string_key():
    with pytest.raises(InvalidDataValueError):
        copy_in({1: "x"})


def test_copy_in_rejects_blocked_member():
    with pytest.raises(InvalidDataValueError):
        copy_in({"__proto__": "x"})
    with pytest.raises(InvalidDataValueError):
        copy_in({"constructor": "x"})


def test_copy_in_rejects_non_plain_type():
    class Foo:
        pass

    with pytest.raises(InvalidDataValueError):
        copy_in(Foo())
    with pytest.raises(InvalidDataValueError):
        copy_in({"a": Foo()})


def test_copy_in_rejects_circular():
    a = {}
    a["self"] = a
    with pytest.raises(InvalidDataValueError):
        copy_in(a)


def test_copy_in_rejects_too_deep():
    # Bangun dict bersarang melebihi MAX_VALUE_DEPTH.
    deep = {}
    cur = deep
    for _ in range(shared.MAX_VALUE_DEPTH + 2):
        cur["next"] = {}
        cur = cur["next"]
    with pytest.raises(InvalidDataValueError):
        copy_in(deep)


def test_copy_in_ok_at_max_depth():
    deep = {}
    cur = deep
    for _ in range(shared.MAX_VALUE_DEPTH):
        cur["next"] = {}
        cur = cur["next"]
    out = copy_in(deep)
    assert out is not None


# ================================================================ registry

def test_register_namespace_and_resolve():
    r = ToolRegistry()
    r.register_namespace("fs", {"read": "read_file", "write": "write_file"})
    assert r.resolve("fs.read") == "read_file"
    assert r.resolve("fs.write") == "write_file"


def test_resolve_unknown_returns_same():
    r = ToolRegistry()
    assert r.resolve("read_file") == "read_file"
    assert r.resolve("tidak.ada") == "tidak.ada"


def test_resolve_alias_precedence():
    r = ToolRegistry()
    r.register_namespace("", {"x": "tool_a"})
    assert r.resolve("x") == "tool_a"


def test_search_empty_query_returns_all():
    r = ToolRegistry()
    r.register_tool("read_file", "Baca isi file")
    r.register_tool("write_file", "Tulis file")
    res = r.search()
    assert res["remaining"] == 0
    paths = {i["path"] for i in res["items"]}
    assert "read_file" in paths
    assert "write_file" in paths


def test_search_filters_by_query():
    r = ToolRegistry()
    r.register_tool("read_file", "Baca isi file")
    r.register_tool("write_file", "Tulis file")
    res = r.search("baca")
    items = res["items"]
    assert len(items) == 1
    assert items[0]["path"] == "read_file"


def test_search_namespace_filter():
    r = ToolRegistry()
    r.register_namespace("fs", {"read": "read_file"})
    r.register_tool("read_file", "Baca file")
    res = r.search(namespace="fs")
    assert all(i["path"].startswith("fs.") for i in res["items"])
    assert res["items"][0]["path"] == "fs.read"


def test_search_pagination():
    r = ToolRegistry()
    for i in range(25):
        r.register_tool(f"tool_{i:02d}", f"deskripsi {i}")
    res1 = r.search(limit=10, offset=0)
    assert len(res1["items"]) == 10
    assert res1["remaining"] == 15
    assert res1["next"] == {"offset": 10}
    res2 = r.search(limit=10, offset=10)
    assert len(res2["items"]) == 10
    assert res2["remaining"] == 5
    res3 = r.search(limit=10, offset=20)
    assert len(res3["items"]) == 5
    assert res3["remaining"] == 0
    assert res3["next"] is None


def test_search_clamps_bad_limit_offset():
    r = ToolRegistry()
    r.register_tool("a", "x")
    res = r.search(limit=0, offset=-5)
    assert len(res["items"]) == 1


def test_search_signature_uses_registered():
    r = ToolRegistry()
    r.register_tool("read_file", "Baca")
    register_signature("read_file", "read_file(path: string) -> string")
    res = r.search("read_file")
    assert res["items"][0]["signature"] == "read_file(path: string) -> string"


def test_signature_fallback():
    r = ToolRegistry()
    r.register_tool("foo", "bar")
    res = r.search("foo")
    assert res["items"][0]["signature"] == "foo(...)"


def test_registry_singleton():
    assert isinstance(REGISTRY, ToolRegistry)


# ================================================================ introspection

def test_parse_simple_description_default_string():
    d = parse_argument_description("path: alamat file")
    assert d["type"] == "string"
    assert d["description"] == "alamat file"
    assert d["required"] is False


def test_parse_typed_description():
    d = parse_argument_description("integer (wajib) - jumlah baris")
    assert d["type"] == "integer"
    assert d["required"] is True


def test_parse_with_default_int():
    d = parse_argument_description("integer (default 10) - limit hasil")
    assert d["type"] == "integer"
    assert d["default"] == 10


def test_parse_with_default_bool():
    d = parse_argument_description("boolean (default true) - aktif")
    assert d["type"] == "boolean"
    assert d["default"] is True


def test_parse_with_default_string():
    d = parse_argument_description("string (default 'abc') - label")
    assert d["default"] == "abc"


def test_parse_unmatched_returns_string():
    d = parse_argument_description("hanya teks tanpa tipe")
    assert d["type"] == "string"
    # Tanpa pola tipe, key 'required' tidak disertakan (default di pemanggil).
    assert "required" not in d


def test_coerce_default():
    assert _coerce_default("42", "integer") == 42
    assert _coerce_default("3.5", "number") == 3.5
    assert _coerce_default("true", "boolean") is True
    assert _coerce_default("no", "boolean") is False
    assert _coerce_default("abc", "integer") == "abc"
    assert _coerce_default("x", "string") == "x"


def test_build_openai_tools_payload():
    tools = {
        "read_file": {
            "schema": {
                "description": "Baca file",
                "arguments": {
                    "path": "string (wajib) - alamat file",
                    "start": "integer (default 1) - baris awal",
                },
            }
        }
    }
    payload = build_openai_tools_payload(tools)
    assert len(payload) == 1
    fn = payload[0]["function"]
    assert fn["name"] == "read_file"
    assert fn["description"] == "Baca file"
    assert fn["parameters"]["type"] == "object"
    assert fn["parameters"]["required"] == ["path"]
    assert fn["parameters"]["properties"]["path"]["type"] == "string"
    assert fn["parameters"]["properties"]["start"]["type"] == "integer"
    assert fn["parameters"]["properties"]["start"]["default"] == 1


# ================================================================ executor

def _ok_handler(**kwargs):
    return f"ok:{kwargs.get('x')}"


def _type_error_handler(**kwargs):
    raise TypeError("missing required argument: 'x'")


def _runtime_error_handler(**kwargs):
    raise tool_error(shared.KIND_INVALID_TOOL_INPUT, "input tidak valid")


def _generic_error_handler(**kwargs):
    raise ValueError("sesuatu meledak")


def test_run_success():
    out = run_tool_with_runtime("t", {"x": 1}, _ok_handler)
    assert out == "ok:1"


def test_run_success_coerces_result_to_str():
    out = run_tool_with_runtime("t", {"x": 1}, lambda **kw: 123)
    assert out == "123"


def test_run_type_error_returns_invalid_input():
    out = run_tool_with_runtime("t", {}, _type_error_handler)
    assert out.startswith("[ERROR] InvalidToolInput")
    assert "tidak sesuai untuk tool 't'" in out


def test_run_runtime_error_propagates():
    out = run_tool_with_runtime("t", {}, _runtime_error_handler)
    assert out.startswith("[ERROR] InvalidToolInput: input tidak valid")


def test_run_generic_exception_returns_invalid_output():
    out = run_tool_with_runtime("t", {}, _generic_error_handler)
    assert out.startswith("[ERROR] InvalidToolOutput")
    assert "gagal" in out


def test_run_copy_in_failure():
    # copy_in menolak argumen non-plain -> error InvalidDataValue.
    class Foo:
        pass

    out = run_tool_with_runtime("t", {"x": Foo()}, _ok_handler)
    assert out.startswith("[ERROR] InvalidDataValue")


def test_run_fires_hooks_on_success():
    events = []
    hooks = ToolCallHooks(
        on_tool_call_start=lambda c: events.append(("start", c.name, c.input)),
        on_tool_call_end=lambda c: events.append(("end", c.outcome, c.duration_ms)),
    )
    run_tool_with_runtime("t", {"x": 1}, _ok_handler, index=3, hooks=hooks)
    assert events[0][:2] == ("start", "t")
    assert events[0][2] == {"x": 1}
    assert events[1][:2] == ("end", "success")
    assert events[1][2] >= 0


def test_run_fires_hooks_on_failure():
    events = []
    hooks = ToolCallHooks(on_tool_call_end=lambda c: events.append(c.outcome))
    run_tool_with_runtime("t", {}, _generic_error_handler, hooks=hooks)
    assert events == ["failure"]


def test_run_fires_end_with_message_on_copy_failure():
    events = []
    hooks = ToolCallHooks(on_tool_call_end=lambda c: events.append(c.message))
    class Foo:
        pass
    run_tool_with_runtime("t", {"x": Foo()}, _ok_handler, hooks=hooks)
    assert len(events) == 1
    assert events[0] is not None
    assert events[0].startswith("[ERROR]")


# ================================================================ web_search (multi-bahasa)

def test_resolve_news_locale_id():
    assert _resolve_news_locale("id") == ("id", "ID", "ID:id")


def test_resolve_news_locale_en():
    assert _resolve_news_locale("en") == ("en", "US", "US:en")


def test_resolve_news_locale_case_insensitive():
    assert _resolve_news_locale("EN") == ("en", "US", "US:en")
    assert _resolve_news_locale("  Id ") == ("id", "ID", "ID:id")


def test_resolve_news_locale_unknown_falls_back_to_state():
    hl, gl, ceid = _resolve_news_locale("fr")
    assert (hl, gl, ceid) == (
        shared_state.GOOGLE_NEWS_HL,
        shared_state.GOOGLE_NEWS_GL,
        shared_state.GOOGLE_NEWS_CEID,
    )


def test_resolve_news_locale_auto_uses_state_default():
    hl, gl, ceid = _resolve_news_locale("auto")
    assert (hl, gl, ceid) == (
        shared_state.GOOGLE_NEWS_HL,
        shared_state.GOOGLE_NEWS_GL,
        shared_state.GOOGLE_NEWS_CEID,
    )


def test_search_rss_passes_lang_params(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["params"] = kwargs["params"]
        class FakeResp:
            def raise_for_status(self):
                pass
            content = b"<rss><channel></channel></rss>"
        return FakeResp()

    monkeypatch.setattr("garwa.tools.web_search._remote_get", fake_get)
    _search_google_news_rss("berita", 5, "en")
    assert captured["params"]["hl"] == "en"
    assert captured["params"]["gl"] == "US"
    assert captured["params"]["ceid"] == "US:en"


def test_tool_web_search_empty_query_returns_error():
    out = tool_web_search("")
    assert out.startswith("[ERROR]")
    assert "query" in out


def test_tool_web_search_auto_falls_back_to_en(monkeypatch):
    calls = []

    def fake_search(query, max_results, lang):
        calls.append(lang)
        if lang == "auto":
            return []  # hasil kosong -> harus fallback ke en
        return [{
            "title": "International headline",
            "url": "https://example.com/x",
            "snippet": "snippet",
            "source": "BBC",
            "published": "Wed, 26 Aug 2026",
        }]

    monkeypatch.setattr("garwa.tools.web_search._search_google_news_rss", fake_search)
    out = tool_web_search("global news")
    assert calls == ["auto", "en"]
    assert "International headline" in out


def test_tool_web_search_explicit_id_no_fallback(monkeypatch):
    calls = []

    def fake_search(query, max_results, lang):
        calls.append(lang)
        return []

    monkeypatch.setattr("garwa.tools.web_search._search_google_news_rss", fake_search)
    out = tool_web_search("berita lokal", lang="id")
    assert calls == ["id"]
    assert "Tidak ada hasil" in out

