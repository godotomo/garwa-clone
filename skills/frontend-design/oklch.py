"""Self-contained OKLCH palette engine for the frontend-design skill.

Implements the color-science reference (references/color-science.md) as
executable, dependency-free code. Pure stdlib, no network, no MCP — keeps
Garwa self-contained.

Public API:
    srgb_to_oklch(r, g, b) -> (L, C, H)
    oklch_to_srgb(L, C, H) -> (r, g, b)
    hex_to_oklch(hex_str)  -> (L, C, H)
    oklch_to_hex(L, C, H)  -> "#rrggbb"
    contrast_ratio(rgb1, rgb2) -> float
    ladder_lighter(L, step) -> float
    ladder_darker(L, step)  -> float
    natural_lightness(hue)  -> float
"""

import math

__all__ = [
    "srgb_to_oklch",
    "oklch_to_srgb",
    "hex_to_oklch",
    "oklch_to_hex",
    "contrast_ratio",
    "ladder_lighter",
    "ladder_darker",
    "natural_lightness",
]


# ---------------------------------------------------------------------------
# Conversion: sRGB <-> OKLCH
# Constants per the CSS Color 4 spec (Björn Ottosson's OKLab).
# ---------------------------------------------------------------------------

def _lin(c: float) -> float:
    """sRGB channel (0..1) -> linear sRGB."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c: float) -> float:
    """Linear sRGB channel -> sRGB (0..1), clamped."""
    c = max(0.0, min(1.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def srgb_to_oklch(r, g, b):
    """r,g,b in 0..255 -> (L, C, H)."""
    r, g, b = _lin(r / 255.0), _lin(g / 255.0), _lin(b / 255.0)
    # linear sRGB -> LMS
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    # cube root
    l_, m_, s_ = l ** (1 / 3), m ** (1 / 3), s ** (1 / 3)
    # LMS -> Lab
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b_ = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    # Lab -> LCH
    C = math.hypot(a, b_)
    H = (math.degrees(math.atan2(b_, a)) + 360) % 360
    return L, C, H


def oklch_to_srgb(L, C, H):
    """(L, C, H) -> (r, g, b) in 0..255."""
    h = math.radians(H)
    a = C * math.cos(h)
    b = C * math.sin(h)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l_3, m_3, s_3 = l_ ** 3, m_ ** 3, s_ ** 3
    # LMS -> linear sRGB
    r = +4.0767416621 * l_3 - 3.3077115913 * m_3 + 0.2309699292 * s_3
    g = -1.2684380046 * l_3 + 2.6097574011 * m_3 - 0.3413193965 * s_3
    b = -0.0041960863 * l_3 - 0.7034186147 * m_3 + 1.7076147010 * s_3
    return (round(_to_srgb(r) * 255), round(_to_srgb(g) * 255), round(_to_srgb(b) * 255))


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def hex_to_oklch(h):
    """'#rrggbb' -> (L, C, H)."""
    return srgb_to_oklch(*_hex_to_rgb(h))


def oklch_to_hex(L, C, H):
    """(L, C, H) -> '#rrggbb'."""
    return "#%02x%02x%02x" % oklch_to_srgb(L, C, H)


# ---------------------------------------------------------------------------
# WCAG contrast gate (local)
# ---------------------------------------------------------------------------

def contrast_ratio(rgb1, rgb2):
    """Contrast ratio between two (r,g,b) tuples in 0..255. >=1.0."""
    def lum(rgb):
        r, g, b = [_lin(c / 255.0) for c in rgb]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    l1, l2 = lum(rgb1), lum(rgb2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


# ---------------------------------------------------------------------------
# Ladders & natural lightness
# ---------------------------------------------------------------------------

def ladder_lighter(L, step):
    """Lighter step: each step travels 10% of the remaining distance to white."""
    return L + (1 - L) * 0.10 * step


def ladder_darker(L, step):
    """Darker step: each step travels 10% of the remaining distance to black."""
    return L - L * 0.10 * step


def natural_lightness(hue):
    """Approx cusp lightness where a hue is most colorful on a screen."""
    table = [
        (25, 0.63), (50, 0.72), (90, 0.97), (140, 0.80),
        (195, 0.72), (260, 0.49), (300, 0.55),
    ]
    # nearest anchor by circular distance
    best_h, best_L = table[0]
    best_d = abs((hue - best_h + 180) % 360 - 180)
    for h, L in table[1:]:
        d = abs((hue - h + 180) % 360 - 180)
        if d < best_d:
            best_h, best_L, best_d = h, L, d
    return best_L
