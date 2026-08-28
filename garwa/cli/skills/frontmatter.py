"""cli/skills/frontmatter.py
Dipecah lebih lanjut dari cli/skills.py.
"""
import os
import re

try:

    import readline  # noqa: F401
except ImportError:
    readline = None


from .. import _state as state



def _parse_skill_frontmatter(skill_md_path: str):
    """Parser YAML-frontmatter minimal: field 'name' dan 'description'
    bertipe string satu baris (boleh dikutip), ATAU block scalar YAML
    ('key: >' folded / 'key: |' literal) yang isinya di baris-baris
    berikutnya dengan indentasi lebih dalam -- format ini umum dipakai
    saat value mengandung ':' yang bisa merusak parsing satu-baris (mis.
    SKILL.md yang menulis 'description: >' lalu isi deskripsi di bawahnya).

    Ini BUKAN parser YAML lengkap (tidak mendukung nested mapping/list,
    anchor, dsb) -- cukup untuk kebutuhan frontmatter skill yang sengaja
    dibuat sederhana (cuma field 'name' dan 'description').
    """
    try:
        with open(skill_md_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None

    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return None
    fm = {}
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        km = re.match(r"^(\w+):\s*(.*)$", line)
        if not km:
            i += 1
            continue
        key, val = km.group(1), km.group(2).strip()

        if val in (">", "|", ">-", "|-", ">+", "|+"):

            block_lines = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() == "":
                    block_lines.append("")
                    i += 1
                    continue
                if nxt[:1] in (" ", "\t"):
                    block_lines.append(nxt.strip())
                    i += 1
                    continue
                break
            if val.startswith(">"):

                paragraphs, buf = [], []
                for bl in block_lines:
                    if bl == "":
                        if buf:
                            paragraphs.append(" ".join(buf))
                            buf = []
                    else:
                        buf.append(bl)
                if buf:
                    paragraphs.append(" ".join(buf))
                val = "\n".join(paragraphs)
            else:

                val = "\n".join(block_lines)
            val = val.strip()
            fm[key] = val
            continue

        if val.startswith('"') and val.endswith('"') and len(val) >= 2:
            val = val[1:-1]
        fm[key] = val
        i += 1
    return fm


def _discover_skill_supporting_files(skill_dir: str):
    """Scan subfolder references/, scripts/, assets/ di dalam satu skill_dir.

    Kembalikan dict {subdir_name: [path_absolut, ...]}, hanya untuk subdir
    yang benar-benar ada dan berisi file. Rekursif ke dalam subdir (mis.
    references/web.md, references/mobile.md) tapi tetap flat dalam hasil
    -- urutan file mengikuti os.walk (top-down, terurut per level lewat
    sorted() manual di bawah).
    """
    found = {}
    for sub in state.SKILL_SUPPORTING_DIRS:
        sub_path = os.path.join(skill_dir, sub)
        if not os.path.isdir(sub_path):
            continue
        files = []
        for root, dirs, filenames in os.walk(sub_path):
            dirs.sort()
            for fname in sorted(filenames):
                if fname.startswith("."):
                    continue
                files.append(os.path.join(root, fname))
                if len(files) >= state.SKILL_SUPPORTING_FILES_LIMIT:
                    break
            if len(files) >= state.SKILL_SUPPORTING_FILES_LIMIT:
                break
        if files:
            found[sub] = files
    return found
