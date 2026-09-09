# Visual Craft: Taste Constraints (Self-Contained)

> **Why this matters.** AI-generated pages share one "generic AI aesthetic" tell stack:
> Inter as the only font, a purple gradient, a pure-white background, and random
> rounded-corner values. The fix is not more skill — it is **taste constraints**. A small
> set of hard rules turns "looks nice but I can't say why" into a checklist you can apply,
> so taste becomes reproducible instead of accidental. This reference encodes the
> battle-tested visual-craft methodology (inspired by PinPin Visual Identity / ppvi and
> Refactoring UI) — fully self-contained, no external MCP or API.
>
> **Core stance: design is not addition, it's selection. Every pixel is an aesthetic
> decision. "Subtracted until right," not "added until pretty."**

---

## 1. Restraint (克制优雅)

**Every visual element must justify itself; if it can't, delete it.**

- No decoration without a job. If you can't answer "what does this shadow/gradient/border
  communicate?", remove it.
- One focal point per screen. Everything else is supporting cast.
- Fewer colors, fewer fonts, fewer effects. Depth comes from subtraction, not accumulation.

**Apply:** after building a screen, do a deletion pass — remove any element that doesn't
earn its place. The design should survive being stripped.

---

## 2. Grayscale Base, Color as Punctuation (灰阶为基)

**Grayscale is the canvas; color is the punctuation. Color ≤ ~15% of the surface.**

- Build the interface in grayscale first (text, surfaces, borders, shadows). It must be
  readable and hierarchical with zero color.
- Then add ONE accent color (the brand/CTA hue) sparingly — buttons, active states,
  links, key data. Color is a spotlight, not a floodlight.
- Reserve the semantic colors (success/error/warning) for status only, not decoration.

**Apply:** if color covers more than ~15% of the visible UI, you've overused it. Pull it
back to the accent + statuses.

---

## 3. Strict Type Hierarchy (严格层级)

**A 5-level type scale, ≥1.4× between levels, consistent within.**

- Define exactly 5 type levels (e.g. display / h1 / h2 / body / caption).
- Each step up is **≥ 1.4×** the previous — enough contrast that the hierarchy is readable
  at a glance (0.5s scan).
- Keep every level consistent across the whole product (same size, weight, line-height per
  level). Never eyeball a one-off size.
- Use `clamp()` for fluid scaling so the hierarchy survives screen sizes.

**Apply:** if two adjacent levels are closer than ~1.4×, they read as the same level —
merge them or push them apart.

---

## 4. Depth & Glassmorphism (玻璃拟态)

**Use light, transparency, and stacking to create real depth — not harsh shadows.**

- Elevation via semi-transparent surface fills and tonal shifts (M3 tonal elevation), not
  heavy drop shadows.
- Glass panels: translucent surface + subtle border + backdrop blur, layered to create
  spatial depth.
- Reserve strong shadows for floating/overlay elements only.

**Apply:** depth should read as physical layering (what's on top), not as decoration.

---

## 5. Density & Breath (密度呼吸)

**The precise balance of information density and whitespace.**

- High-density screens (dashboards, data, DevTools) need deliberate breathing room between
  groups — whitespace is what makes density legible.
- Low-density screens (landing, editorial) need enough density to feel substantial, not
  empty.
- Use a consistent spacing scale (4/8/12/16/24/32/48) — never random gaps.

**Apply:** if a screen feels cramped, add spacing before adding borders; if it feels empty,
add useful content, not decoration.

---

## 6. Anti-Patterns (the "generic AI" tell stack — NEVER ship)

| Anti-pattern | Why it reads as generic | Fix |
|---|---|---|
| **Inter / Roboto / Arial / system-ui as display** | The most overused AI font | Pick a characterful display font (see SKILL.md §8) |
| **Purple gradient hero** | The default "AI" gradient | A restrained accent on grayscale, or one domain-grounded hue |
| **Pure-white background everywhere** | Flat, no depth | Off-white surface + subtle tonal elevation |
| **Random rounded-corner values** | Inconsistent, unconsidered | One radius token per element type (card vs button) |
| **Color everywhere** | No hierarchy, no focus | Grayscale base + ≤15% color |
| **Uniform huge rounded corners** | The "AI card" look | Vary radius by role; small for buttons, larger for cards |

---

## 7. The 0.5-second Scan Test

Before shipping, ask: **can a user grasp the hierarchy in half a second?**

- What's the single most important thing on this screen? Is it the visual anchor?
- Does the eye know where to look first, second, third — without reading anything?
- Is there exactly one clear primary action?

If the scan fails, the hierarchy is wrong regardless of how polished the details are.
Fix hierarchy before polish.
