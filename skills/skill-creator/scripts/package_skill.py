#!/usr/bin/env python3
"""Package a skill folder into a `.skill` file.

The `.skill` format is a zip archive of the skill directory (SKILL.md plus any
supporting files such as references/, agents/, scripts/, assets/, evals/).

Usage:
    python -m scripts.package_skill <path/to/skill-folder> [--output DIR] [--name NAME]

The output file is written to the current directory by default (or to --output),
named `<skill-name>.skill` where the name comes from the skill's directory name
or the `name` frontmatter field (--name overrides both).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from pathlib import Path


def read_skill_name(skill_dir: Path) -> str | None:
    """Extract the `name` frontmatter field from SKILL.md, if present."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    text = skill_md.read_text(encoding="utf-8")
    m = re.search(r"^name:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip().strip('"').strip("'")


def package(skill_dir: Path, output_dir: Path, name: str | None) -> Path:
    if not skill_dir.is_dir():
        raise SystemExit(f"error: not a directory: {skill_dir}")
    if not (skill_dir / "SKILL.md").exists():
        raise SystemExit(f"error: {skill_dir} has no SKILL.md")

    skill_name = name or read_skill_name(skill_dir) or skill_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{skill_name}.skill"

    # Stage into a temp dir first when packaging manually, then move into place.
    # Direct writes to the destination may fail due to permissions (see
    # references/environment-guide.md "Updating an existing skill").
    import tempfile

    tmp_fd, tmp_path = tempfile.mkstemp(prefix=f"{skill_name}.", suffix=".skill")
    try:
        with os.fdopen(tmp_fd, "wb") as tmp_file:
            with zipfile.ZipFile(tmp_file, "w", zipfile.ZIP_DEFLATED) as zf:
                for path in sorted(skill_dir.rglob("*")):
                    if path.is_file():
                        zf.write(path, arcname=path.relative_to(skill_dir))
        os.replace(tmp_path, out_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Package a skill folder into a .skill file")
    parser.add_argument("skill_dir", type=Path, help="Path to the skill folder")
    parser.add_argument("--output", type=Path, default=Path("."), help="Output directory (default: current dir)")
    parser.add_argument("--name", type=str, default=None, help="Override the .skill filename")
    args = parser.parse_args(argv)

    out_path = package(args.skill_dir, args.output, args.name)
    print(f"Packaged {args.skill_dir} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
