"""cli/markdown_render/inline.py
Dipecah lebih lanjut dari cli/markdown_render.py.
"""
import re
import sys

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from ..colors import C
from .latex import _latex_to_unicode



def _render_inline_markdown(text: str) -> str:
    """Render markdown + LaTeX pada teks biasa; code tidak diproses."""
    if not sys.stdout.isatty() or not text:
        return text

    text = text.replace("\x1b", "")
    placeholders = []

    def stash_code(match):
        idx = len(placeholders)

        placeholders.append(f"{C.CODE}{match.group(1)}{C.RESET}")
        return f"\x00CODE{idx}\x00"

    text = re.sub(r"`([^`\n]+)`", stash_code, text)

    text = _latex_to_unicode(text)

    text = re.sub(r"\*\*(.+?)\*\*", lambda m: f"{C.BOLD}{m.group(1)}{C.RESET}", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)",
                  lambda m: f"{C.BOLD}{m.group(1)}{C.RESET}", text)
    text = re.sub(r"(?<!_)_([^_\n]+)_(?!_)",
                  lambda m: f"{C.BOLD}{m.group(1)}{C.RESET}", text)

    text = re.sub(r"\[([^]\n]+)\]\(([^)\n]+)\)",
                  lambda m: f"{m.group(1)} ({m.group(2)})", text)

    m = re.match(r"^(#{1,6})\s+(.*)$", text)
    if m:
        text = f"{C.BOLD}{m.group(2)}{C.RESET}"

    if re.match(r"^\s*>\s?", text):
        text = re.sub(r"^\s*>\s?", "│ ", text, count=1)
        text = f"{C.DIM}{text}{C.RESET}"
    else:
        text = re.sub(r"^(\s*)[-*+]\s+", r"\1• ", text)
        text = re.sub(r"^(\s*)\d+\.\s+", r"\1• ", text)

    for i, value in enumerate(placeholders):
        text = text.replace(f"\x00CODE{i}\x00", value)
    return text
