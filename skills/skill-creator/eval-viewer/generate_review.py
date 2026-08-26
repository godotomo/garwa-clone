#!/usr/bin/env python3
"""Generate a self-contained HTML eval review page from an iteration's results.

Collects the quantitative benchmark (benchmark.json) together with the
qualitative per-eval outputs (prompt, output files, formal grades) and any
previous-iteration feedback, then either:

  * starts a local HTTP server and opens it in the browser (default), or
  * writes a standalone HTML file (--static) for headless/Cowork setups.

The generated page has two tabs:
  * "Outputs" — click through each test case, view the prompt + output files,
    see previous output / previous feedback (iteration 2+), and leave feedback
    in a textbox that auto-saves. "Submit All Reviews" saves feedback.json.
  * "Benchmark" — the quantitative comparison (pass rates, timing, tokens).

Usage:
    python eval-viewer/generate_review.py <workspace>/iteration-<N> \
        [--skill-name "my-skill"] \
        [--benchmark <workspace>/iteration-<N>/benchmark.json] \
        [--previous-workspace <workspace>/iteration-<N-1>] \
        [--static <output.html>] \
        [--template assets/eval_review.html] \
        [--port 8000]
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

TEXT_EXT = {
    ".md", ".txt", ".csv", ".json", ".html", ".htm", ".xml", ".py", ".js",
    ".ts", ".css", ".log", ".yaml", ".yml", ".toml", ".ini", ".sh", ".sql",
    ".svg", ".rst", ".txt",
}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif"}
MAX_TEXT_BYTES = 100_000  # avoid embedding huge text files into the HTML


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _read_outputs(outputs_dir: Path) -> list[dict]:
    """Read an outputs/ directory into a list of renderable entries."""
    if not outputs_dir.is_dir():
        return []
    entries: list[dict] = []
    for p in sorted(outputs_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(outputs_dir).as_posix()
        ext = p.suffix.lower()
        try:
            if ext in IMAGE_EXT:
                data = base64.b64encode(p.read_bytes()).decode("ascii")
                mime = mimetypes.guess_type(p.name)[0] or "image/png"
                entries.append({
                    "name": rel,
                    "kind": "image",
                    "content": f"data:{mime};base64,{data}",
                })
            elif ext in TEXT_EXT:
                content = p.read_text(encoding="utf-8", errors="replace")
                if len(content.encode("utf-8")) > MAX_TEXT_BYTES:
                    content = content[:MAX_TEXT_BYTES] + "\n… [truncated]"
                entries.append({"name": rel, "kind": "text", "content": content})
            else:
                entries.append({
                    "name": rel,
                    "kind": "file",
                    "content": "",
                })
        except OSError:
            entries.append({"name": rel, "kind": "file", "content": ""})
    return entries


def _read_grades(run_dir: Path) -> list[dict]:
    grading = run_dir / "grading.json"
    if not grading.exists():
        return []
    data = _load_json(grading)
    return data.get("expectations", [])


def _previous_feedback(prev_workspace: Path, eval_name: str, config: str) -> str:
    """Look up the user's feedback for a run in the previous iteration."""
    fb_path = prev_workspace / "feedback.json"
    if not fb_path.exists():
        return ""
    try:
        reviews = _load_json(fb_path).get("reviews", [])
    except (OSError, json.JSONDecodeError):
        return ""
    target = f"{eval_name}-{config}"
    for r in reviews:
        if r.get("run_id") == target:
            return r.get("feedback", "")
    return ""


def _collect_eval(
    iteration_dir: Path,
    eval_name: str,
    configs: list[str],
    previous_workspace: Path | None,
) -> dict:
    """Collect prompt, per-config outputs + grades, and previous data for one eval."""
    eval_dir = iteration_dir / eval_name
    prompt = ""
    meta = eval_dir / "eval_metadata.json"
    if meta.exists():
        prompt = _load_json(meta).get("prompt", "")

    runs = []
    for config in configs:
        run_dir = eval_dir / config
        runs.append({
            "name": config,
            "outputs": _read_outputs(run_dir / "outputs"),
            "grades": _read_grades(run_dir),
        })

    previous_outputs: list[dict] = []
    previous_feedback = ""
    if previous_workspace is not None:
        # Previous output: reuse the with_skill run of the prior iteration.
        prev_with = previous_workspace / eval_name / "with_skill" / "outputs"
        previous_outputs = _read_outputs(prev_with)
        previous_feedback = _previous_feedback(
            previous_workspace, eval_name, "with_skill"
        )

    return {
        "eval_name": eval_name,
        "prompt": prompt,
        "runs": runs,
        "previous_outputs": previous_outputs,
        "previous_feedback": previous_feedback,
    }


def build_viewer_data(
    iteration_dir: Path,
    benchmark: dict,
    previous_workspace: Path | None = None,
) -> dict:
    """Assemble the full payload injected into the HTML template."""
    configs = [c["name"] for c in benchmark.get("configs", [])]
    eval_names: list[str] = []
    for cfg in benchmark.get("configs", []):
        for ev in cfg.get("evals", []):
            if ev["eval_name"] not in eval_names:
                eval_names.append(ev["eval_name"])

    evals = [
        _collect_eval(iteration_dir, name, configs, previous_workspace)
        for name in eval_names
    ]

    return {
        "skill_name": benchmark.get("skill_name", ""),
        "iteration": benchmark.get("iteration", 0),
        "benchmark": benchmark,
        "evals": evals,
    }


def generate(
    iteration_dir: Path,
    template_path: Path,
    benchmark_path: Path | None = None,
    previous_workspace: Path | None = None,
    out_path: Path | None = None,
) -> Path:
    """Build the review HTML and write it to out_path (default: iteration dir)."""
    if benchmark_path is None:
        benchmark_path = iteration_dir / "benchmark.json"
    if not benchmark_path.exists():
        raise FileNotFoundError(f"benchmark.json not found: {benchmark_path}")
    if not template_path.exists():
        raise FileNotFoundError(f"template not found: {template_path}")

    benchmark = _load_json(benchmark_path)
    data = build_viewer_data(iteration_dir, benchmark, previous_workspace)

    payload = json.dumps(data, ensure_ascii=False, indent=2)
    template = template_path.read_text(encoding="utf-8")
    html = template.replace("__VIEWER_DATA__", payload)

    if out_path is None:
        out_path = iteration_dir / "eval_review.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


class _FeedbackHandler(BaseHTTPRequestHandler):
    """Serves the generated HTML and accepts feedback.json POSTs."""

    html = b""

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, type(self).html)
        else:
            self._send(404, b"not found")

    def do_POST(self):
        if self.path != "/feedback":
            self._send(404, b"not found")
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            feedback = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, b"invalid json")
            return
        feedback_path = self.server.feedback_path  # type: ignore[attr-defined]
        feedback_path.write_text(
            json.dumps(feedback, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self._send(200, b"ok", "text/plain")

    def log_message(self, *args):  # silence request logging
        pass


def serve(html_path: Path, port: int = 0) -> HTTPServer:
    """Start an HTTP server serving the generated HTML; returns the server."""
    html = html_path.read_bytes()
    handler = type("Handler", (_FeedbackHandler,), {"html": html})

    server = HTTPServer(("127.0.0.1", port), handler)
    # Store the feedback destination so the handler can resolve it.
    server.feedback_path = html_path.parent / "feedback.json"  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate (and optionally serve) an eval review page"
    )
    parser.add_argument("iteration_dir", type=Path, help="Path to <workspace>/iteration-<N>")
    parser.add_argument("--skill-name", default=None, help="Name of the skill (optional; falls back to benchmark.json)")
    parser.add_argument("--benchmark", type=Path, default=None, help="Path to benchmark.json (default: <iteration_dir>/benchmark.json)")
    parser.add_argument("--previous-workspace", type=Path, default=None, help="Path to the previous iteration directory")
    parser.add_argument("--static", type=Path, default=None, help="Write a standalone HTML file instead of starting a server")
    parser.add_argument("--template", type=Path, default=None, help="Path to the eval_review.html template")
    parser.add_argument("--port", type=int, default=0, help="Port for the local server (0 = auto)")
    args = parser.parse_args(argv)

    if not args.iteration_dir.is_dir():
        print(f"error: not a directory: {args.iteration_dir}", file=sys.stderr)
        return 1

    template = args.template or (Path(__file__).resolve().parent.parent / "assets" / "eval_review.html")

    try:
        out = generate(
            args.iteration_dir,
            template,
            benchmark_path=args.benchmark,
            previous_workspace=args.previous_workspace,
            out_path=args.static,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.static is not None:
        print(f"Wrote static HTML: {out}")
        return 0

    # Server mode: serve and open in the browser.
    try:
        server = serve(out, port=args.port)
    except OSError as e:
        print(f"error: could not start server: {e}", file=sys.stderr)
        return 1
    host, port = server.server_address
    url = f"http://{host}:{port}/"
    print(f"Serving {out} at {url}")
    print(f"Feedback will be saved to {out.parent / 'feedback.json'}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        webbrowser.open(url)
    except Exception as e:  # noqa: BLE001
        print(f"warning: could not open browser: {e}", file=sys.stderr)
    print("Press Ctrl-C to stop the viewer.")
    try:
        while True:
            import time
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()
        return 0


if __name__ == "__main__":
    sys.exit(main())
