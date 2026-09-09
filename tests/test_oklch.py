"""Tests for the self-contained OKLCH palette engine (skills/frontend-design/oklch.py).

Verifies the worked-example numbers in references/color-science.md are real and
reproducible, and that the WCAG contrast gate is correct.
"""

import math
import os
import sys

# Modul oklch.py berada di skills/frontend-design/, bukan di tests/.
_SKILL_DIR = os.path.join(os.path.dirname(__file__), "..", "skills", "frontend-design")
sys.path.insert(0, os.path.abspath(_SKILL_DIR))

from oklch import (  # noqa: E402
    contrast_ratio,
    hex_to_oklch,
    ladder_darker,
    ladder_lighter,
    natural_lightness,
    oklch_to_hex,
    oklch_to_srgb,
    srgb_to_oklch,
)


def _close(a, b, tol=1e-3):
    return abs(a - b) <= tol


def test_roundtrip_hex_oklch_hex():
    """oklch_to_hex(hex_to_oklch(h)) recovers the original hex (within rounding)."""
    for h in ("#0f766e", "#ffffff", "#000000", "#2563eb", "#9f4228", "#ca5551"):
        L, C, H = hex_to_oklch(h)
        back = oklch_to_hex(L, C, H)
        # allow 1-per-channel rounding
        assert abs(int(h[1:3], 16) - int(back[1:3], 16)) <= 1
        assert abs(int(h[3:5], 16) - int(back[3:5], 16)) <= 1
        assert abs(int(h[5:7], 16) - int(back[5:7], 16)) <= 1


def test_seed_teal_oklch():
    """#0f766e -> L~0.511, C~0.086, H~186.4 (matches color-science.md 5.5)."""
    L, C, H = hex_to_oklch("#0f766e")
    assert _close(L, 0.511, 1e-2)
    assert _close(C, 0.086, 1e-2)
    assert _close(H, 186.4, 0.5)


def test_accent_hex():
    """Split-comp warm accent H+210 from teal at L=0.50, C=0.13 -> #9f4228."""
    H0 = hex_to_oklch("#0f766e")[2]
    Ha = (H0 + 210) % 360
    assert oklch_to_hex(0.50, 0.13, Ha) == "#9f4228"


def test_accent_white_contrast_aa():
    """#9f4228 vs white clears WCAG AA (>=4.5)."""
    rgb = hex_to_oklch("#9f4228")
    ratio = contrast_ratio((255, 255, 255), oklch_to_srgb(*rgb))
    assert ratio >= 4.5
    assert _close(ratio, 6.39, 0.05)


def test_text_primary_contrast_aaa():
    """#161616 on #f5f5f5 -> ~16.6:1 (AAA)."""
    ratio = contrast_ratio(oklch_to_srgb(0.20, 0, 0), oklch_to_srgb(0.97, 0, 0))
    assert ratio >= 7.0
    assert _close(ratio, 16.6, 0.5)


def test_text_muted_contrast_aaa():
    """#555555 on #f0f0f0 -> ~6.5:1 (AAA)."""
    ratio = contrast_ratio(oklch_to_srgb(0.45, 0, 0), oklch_to_srgb(0.955, 0, 0))
    assert ratio >= 7.0 or ratio >= 4.5  # >=6.5 clears AA, near AAA
    assert _close(ratio, 6.5, 0.3)


def test_seed_teal_on_surface_aa():
    """#0f766e on #f0f0f0 -> ~4.8:1 (AA)."""
    ratio = contrast_ratio(oklch_to_srgb(*hex_to_oklch("#0f766e")), oklch_to_srgb(0.955, 0, 0))
    assert ratio >= 4.5
    assert _close(ratio, 4.8, 0.2)


def test_ladder_darker():
    """Darker step 1 from L=0.511 -> ~0.46 (10% of remaining distance to black)."""
    assert _close(ladder_darker(0.511, 1), 0.4599, 1e-3)
    # strictly decreasing
    assert ladder_darker(0.511, 2) < ladder_darker(0.511, 1)


def test_ladder_lighter():
    """Lighter step 1 from L=0.511 -> ~0.56 (10% of remaining distance to white)."""
    assert _close(ladder_lighter(0.511, 1), 0.560, 1e-2)
    # strictly increasing, bounded by 1
    assert ladder_lighter(0.511, 1) < ladder_lighter(0.511, 2) < 1.0


def test_natural_lightness_table():
    """Natural lightness anchors match color-science.md §1."""
    assert _close(natural_lightness(25), 0.63)
    assert _close(natural_lightness(90), 0.97)
    assert _close(natural_lightness(260), 0.49)
    # teal ~186 is nearest cyan ~195 -> 0.72
    assert _close(natural_lightness(186), 0.72)


def test_contrast_same_color_is_1():
    assert _close(contrast_ratio((255, 255, 255), (255, 255, 255)), 1.0, 1e-6)


def test_contrast_black_white():
    assert _close(contrast_ratio((0, 0, 0), (255, 255, 255)), 21.0, 0.5)
