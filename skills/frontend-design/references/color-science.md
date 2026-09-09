# Color Science: OKLCH Palette Engine (Self-Contained)

> **Why OKLCH, not HSL.** HSL is quick to compute but misleading to look at: ask HSL
> for yellow and blue at the *same* lightness and you get a yellow that blinds you next
> to a blue you can barely see. The numbers match; your eye disagrees. OKLCH is built so
> **equal numbers look equal** — lightness is perceptual, and colorfulness is a separate
> `chroma` axis. This is the engine behind the palette generators people actually pay for
> (ColorPalette Pro, tints.dev, adamculpepper/color-palette), and it runs **entirely
> locally** — no API, no MCP, no network. That keeps Garwa self-contained.
>
> Use this reference to generate a **unique, domain-grounded palette per project** instead
> of copying a canned hex list. The result reads as professionally shipped, never template.

---

## 1. The OKLCH axes

A color is `oklch(L C H)`:

- **L** — perceptual lightness, `0` (black) → `1` (white). Equal L = equal perceived brightness.
- **C** — chroma (colorfulness), `0` (gray) → ~`0.4` (most vivid sRGB can show).
- **H** — hue, `0`–`360` degrees around the wheel.

### Natural lightness (the "yellow is not mustard" rule)

Each hue has a lightness where it is *most colorful on a screen*. Force one flat lightness
across all hues and yellow collapses into brown/mustard. Use the cusp lightness per hue:

| Hue | Natural lightness (approx) |
|---|---|
| Red (~25°) | ~0.63 |
| Orange (~50°) | ~0.72 |
| Yellow (~90°) | ~0.97 |
| Green (~140°) | ~0.80 |
| Cyan (~195°) | ~0.72 |
| Blue (~260°) | ~0.49 |
| Violet (~300°) | ~0.55 |

When building a multi-hue palette (analogous/complementary/triad), set each color's L to
its natural lightness first, then nudge L by the same delta to darken/lighten the whole
family. Never hold one L constant across hues.

---

## 2. Harmony modes (where the hues go)

Pick a base hue `H`, then place accent hues on the wheel:

| Mode | Hue offsets from base H |
|---|---|
| **Analogous** | H, H±15°, H±30° (a ~60–90° fan; stays neighbors, safe) |
| **Complementary** | H, H+180° (strongest contrast; use one as accent only) |
| **Split-complementary** | H, H+150°, H+210° (softer than full complement) |
| **Triadic** | H, H+120°, H+240° (balanced, playful) |
| **Tetradic** | H, H+90°, H+180°, H+270° (rich, needs restraint) |
| **Monochrome** | one hue, vary L only |

**Rule:** for UI, pick **one dominant hue + one accent** (complementary or split-complementary
for the CTA). A triadic/tetradic full palette is for brand illustration, not UI chrome —
too many hues reads as noise.

---

## 3. Ladders (tints & shades — the "10% lighter" rule)

"Do not add 10 to the lightness number." Each step travels **10% of the remaining distance**
to white (lighter) or black (darker). A pale color keeps getting lighter without clipping;
a near-black shades to something still colorful, not flat `#000`.

```
L_step_lighter = L + (1 - L) * 0.10 * step
L_step_darker  = L - L * 0.10 * step
```

Hold chroma `C` at the base value through the ladder; pull it back only when a step would
land outside what a screen can show (the ends soften on their own). Stop ladders at ~95%
of the way so no rung is pure white or pure black.

---

## 4. Harmonize / unify (make a family)

Six unrelated colors read as noise; a palette pulled toward a common center reads as a set.

- **Unify** — slide every hue toward the palette's average hue AND every chroma toward the
  average chroma. A little pull makes pasted colors cohere; too much collapses them into one.
- **Preserve neutrals** — gray has no meaningful hue (its hue reading is arithmetic noise).
  Any color under ~`0.02` chroma must stay exactly where it is. Dragging `#c9c9c9` toward the
  palette average turns it beige — never do that.
- **Temperature / saturation / lightness / contrast** dials — separate adjustments to nudge
  the whole family after unify.

---

## 5. Practical recipe for a Garwa UI palette

Given a domain (see `domain-archetypes.md`) and a **seed color** (brand hex, or a color
evoked by the domain), produce a full token set:

1. **Parse the seed** to OKLCH (convert hex → sRGB → OKLCH; see §6).
2. **Pick the accent** — from the seed hue, take the complementary or split-complementary
   hue. Set its L to its natural lightness, then tune C so it passes the WCAG contrast gate
   (§7) against the surface it sits on.
3. **Build the neutral ramp** — a monochrome gray ladder (L from ~0.97 down to ~0.05, C≈0)
   for `--bg-base`, `--bg-surface`, `--bg-surface-elevated`, `--text-primary`, `--text-muted`,
   `--border-subtle`. Keep neutrals truly neutral (C < 0.02) so they never drift beige.
4. **Derive the semantic tokens** — success/error/warning from hue families (green ~150°,
   red ~25°, amber ~75°) at natural lightness, tuned for contrast.
5. **Unify lightly** — pull the brand + accent + semantic hues toward a common chroma so the
   whole set reads as one family, while preserving the neutrals.
6. **Export** as `:root` CSS variables (see SKILL.md §7), keeping light as the base and a
   `.dark` override only when the domain requires it.

**Result:** a palette that is *derived from the project's seed*, not copied from a table —
unique per project, perceptually balanced, and accessible.

---

## 6. Hex → OKLCH conversion (reference)

sRGB → linear sRGB → LMS → OKLCH. Constants per the CSS Color 4 spec (Björn Ottosson's OKLab):

```python
import math

def srgb_to_oklch(r, g, b):  # r,g,b in 0..255
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = lin(r), lin(g), lin(b)
    # linear sRGB -> LMS
    l = 0.4122214708*r + 0.5363325363*g + 0.0514459929*b
    m = 0.2119034982*r + 0.6806995451*g + 0.1073969566*b
    s = 0.0883024619*r + 0.2817188376*g + 0.6299787005*b
    # cube root
    l_, m_, s_ = l**(1/3), m**(1/3), s**(1/3)
    # LMS -> Lab
    L = 0.2104542553*l_ + 0.7936177850*m_ - 0.0040720468*s_
    a = 1.9779984951*l_ - 2.4285922050*m_ + 0.4505937099*s_
    b_ = 0.0259040371*l_ + 0.7827717662*m_ - 0.8086757660*s_
    # Lab -> LCH
    C = math.hypot(a, b_)
    H = (math.degrees(math.atan2(b_, a)) + 360) % 360
    return L, C, H
```

---

## 7. WCAG contrast gate (local, no API)

Compute contrast ratio in-code so you never ship a color that fails:

```python
def contrast_ratio(rgb1, rgb2):
    def lum(rgb):
        def lin(c): return c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4
        r,g,b = [lin(c) for c in rgb]
        return 0.2126*r + 0.7152*g + 0.0722*b
    l1, l2 = lum(rgb1), lum(rgb2)
    if l1 < l2: l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)
# pass if ratio >= 4.5 (body), >= 3.0 (large text / UI borders), >= 7.0 (GovTech body)
```

Always verify accent-on-surface and text-on-surface pairs against the gate **before** shipping.
