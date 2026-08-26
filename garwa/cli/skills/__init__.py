"""cli/skills/__init__.py
Re-export API publik supaya `from .skills import X`
di file lain tetap bekerja tanpa perubahan setelah dipecah lebih lanjut.
"""
from .frontmatter import _parse_skill_frontmatter, _discover_skill_supporting_files
from .discovery import discover_skills, _shorten_skill_description, _build_skills_section
from .system_prompt import build_system_prompt
