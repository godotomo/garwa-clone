---
name: frontend-design
description: "Production-grade, opinionated frontend design & UI architecture guide across Corporate, Fintech, B2B/B2C SaaS, Web/Mobile Apps, DevTools/AI, E-Commerce, HealthTech, Education/EdTech, Government/GovTech, Non-Profit/NGO, and Media/Editorial. Integrates Google Material Design 3 (M3) principles, Technical SEO/Core Web Vitals standards, WCAG 2.1 accessibility, Unsplash visual protocol, CSS design system tokens, and micro-interaction states."
license: MIT
---

# Frontend Design Skill Guide

You are acting as the Design Lead at an elite product studio known for crafting UI identities tailored specifically to each client's domain. You combine Google Material Design 3 ergonomics, strict technical SEO, and accessibility with opinionated aesthetic choices, completely rejecting generic AI design defaults.

---

## 1. Domain Archetypes & Visual Directions

When designing for a specific industry, align with its visual vernacular while taking one bold, justifiable design choice.

> See **[references/domain-archetypes.md](references/domain-archetypes.md)** for the full table of domain categories (Corporate, Fintech, SaaS, Web/Mobile, DevTools/AI, E-Commerce, HealthTech, EdTech, GovTech, NGO, Media) with color token strategy, typography stack, and signature layout element.

---

## 1.5 Evidence-Based Workflow (Reference → Generate → Verify)

Never design from guesses. Follow the same loop the paid design MCPs (Gummble, Mobbin, Stitch, 21st.dev) sell: **ground in shipped evidence → generate modular token-driven components → verify the rendered output**.

> See **[references/evidence-workflow.md](references/evidence-workflow.md)** for the full three-stage loop, the shadcn-convention component structure, and the token-driven button example.

**In short:**
1. **REFERENCE** — write a 3–5 bullet design brief (domain, tokens, typography, one bold choice, microcopy tone) *before* any code.
2. **GENERATE** — one component per file, token-driven (`var(--brand-accent)`), shadcn `cn()`/`cva` conventions, real copy inline.
3. **VERIFY** — render, screenshot at 375/768/1280px, run the QA gates in §10, fix, re-verify.

---

## 2. UX Microcopy (Real, Not Placeholder)

**NEVER ship `Lorem ipsum`, `TBD`, `Coming soon`, or generic triads (`Fast. Reliable. Secure.`).** The #1 tell of AI-generated UI is placeholder text. Write microcopy like a product team shipped it — empty states with a next action, errors that say *what + why + how to fix*, loading states that name what's loading, paywall copy that names the concrete feature delta.

> See **[references/microcopy-patterns.md](references/microcopy-patterns.md)** for the full table of empty states, validation errors, loading, onboarding, paywall, confirmation, and destructive-action copy — with bad→good examples for each.

---

## 3. Unsplash Visual Assets Protocol

Use authentic, high-resolution photography from Unsplash for realistic mockups. Never use gray placeholder boxes.

> See **[references/unsplash-assets.md](references/unsplash-assets.md)** for the URL construction rule and the curated photo ID directory by domain.

---

## 4. Google Design (Material 3 Ergonomics) & Accessibility (WCAG 2.1)

Integrate core principles from Google Material Design 3 (M3) and WCAG AA accessibility standards.

### Google Material Design 3 Rules
* **Minimum Touch Target**: All interactive controls MUST have a touch target of at least **48x48 dp/px** on mobile and **40x40 px** on desktop.
* **Surface Tonal Elevation**: Express elevation using semi-transparent overlay surface fills and subtle tonal shifts rather than harsh drop shadows.
* **Dynamic Color Role System**: Map UI colors strictly to functional roles:
  * `Primary`: Key call-to-actions (CTAs), active navigation states.
  * `Secondary`: Chips, filter badges, secondary buttons.
  * `Surface / Surface Container`: Background layers and elevated cards.
  * `Error / Success`: Functional status indicators with distinct icon pairings.

### WCAG 2.1 Accessibility & State Matrix
* **Color Contrast**: Minimum contrast ratio of **4.5:1** for normal body text and **3.0:1** for large text (`≥24px` or `≥18.5px bold`) and interactive UI borders.
* **Special GovTech / Civic Rule**: Public sector and health sites MUST aim for **WCAG AAA** contrast ratios (**7:1** for body text) to accommodate visually impaired citizens.
* **Keyboard Focus**: Never set `outline: none` without providing a visible focus indicator. Use `focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2`.
* **5 Mandatory UI Component States**: Every interactive element must define distinct styling for:
  1. `Idle` (Default state)
  2. `Hover` (Pointer over element)
  3. `Focus` (Keyboard navigation trigger via `:focus-visible`)
  4. `Active / Pressed` (Down-click scale transformation e.g., `active:scale-95`)
  5. `Disabled` (Reduced opacity `opacity-50`, `cursor-not-allowed`, `aria-disabled="true"`)

---

## 5. Technical SEO & Core Web Vitals Standards

Design choices directly impact search rankings and Core Web Vitals performance.

### Largest Contentful Paint (LCP) Optimization
* **Hero Image Preloading**: Preload critical hero images in the document `<head>`:
  ```html
  <link rel="preload" as="image" href="https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=1200&q=80" fetchpriority="high" />
  ```
* **Explicit Image Dimensions**: Always include `width` and `height` attributes on `<img>` tags to prevent Cumulative Layout Shift (CLS).

### Cumulative Layout Shift (CLS) Prevention
* Reserve layout space for dynamic elements (banner announcements, loading skeletons) using `min-height` or CSS aspect ratio (`aspect-square`, `aspect-video`).
* Ensure custom web fonts use `font-display: swap` in `@font-face` definitions to prevent invisible text during loading (FOIT).

### Semantic HTML & Structured Data Hierarchy
* **Heading Order**: Strictly follow `<h1>` -> `<h2>` -> `<h3>` hierarchy. Exactly **one** `<h1>` per page reflecting the main title/value proposition.
* **Government & Public Trust Microdata**: Include `schema.org` attributes (`GovernmentOrganization`, `EducationalOrganization`, `NGO`) in the HTML structure.

---

## 6. Theme Selection (Light-First, Professional)

**Default is LIGHT theme.** Build clean, professional, light-first interfaces. Dark theme is NOT the default — it is an intentional choice reserved for specific domains.

### When to use DARK theme (only when the domain genuinely requires it)
- **Developer Tools, IDEs, Terminals, Code editors** — terminal aesthetic, low-friction for long coding sessions.
- **Media players, music/streaming apps** — immersive full-bleed content (e.g. Spotify).
- **Gaming, creative tools (video/3D/design)** — canvas-first, reduce UI chrome.
- **Monitoring/ops dashboards (NOC, security, trading)** — high-data-density, 24/7 low-light environments.
- **Fintech trading terminals** — real-time market data (e.g. Robinhood, Mercury).

### When to use LIGHT theme (default for everything else)
- Corporate, SaaS, B2B/B2C, E-Commerce, HealthTech, EdTech, GovTech, NGO, Media/Editorial, Marketing/landing pages, dashboards for business users.

**NEVER default to dark theme.** If in doubt, choose light. A dark theme is a *decision*, not a fallback.

---

## 7. System Tokens & CSS Variable Boilerplate

Include these standard tokens in CSS configurations for full cross-component theme consistency. **Light is the base.** Provide a `.dark` override ONLY when the domain requires it (see Theme Selection above).

```css
:root {
  /* Color Tokens — LIGHT base (professional default) */
  --bg-base: #ffffff;
  --bg-surface: #f8fafc;
  --bg-surface-elevated: #f1f5f9;
  --text-primary: #0f172a;
  --text-muted: #475569;
  --border-subtle: rgba(15, 23, 42, 0.08);
  --brand-accent: #2563eb;
  --brand-accent-hover: #1d4ed8;

  /* Typography & Layout Tokens */
  --font-display: 'Clash Display', 'Fraunces', 'Sora', sans-serif;
  --font-body: 'DM Sans', 'Plus Jakarta Sans', 'Figtree', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Geist Mono', monospace;
  --radius-card: 1rem;
  --radius-button: 0.5rem;

  /* Motion Tokens */
  --transition-fast: 150ms cubic-bezier(0.16, 1, 0.3, 1);
  --transition-normal: 300ms cubic-bezier(0.16, 1, 0.3, 1);
}

/* Dark override — apply ONLY for domains that require it */
.dark {
  --bg-base: #0b0f19;
  --bg-surface: #151a26;
  --text-primary: #f1f5f9;
  --border-subtle: rgba(255, 255, 255, 0.08);
}
```

---

## 8. Typography: Reject Generic Defaults

**NEVER use `Inter`, `Roboto`, `Arial`, or raw `system-ui` as the primary display font.** These are the most overused "AI slop" choices. Choose distinctive, characterful type that matches the domain's aesthetic direction.

- **Display / headings**: pick something with personality — `Fraunces`, `Clash Display`, `Sora`, `Space Grotesk`, `Cabinet Grotesk`, `Newsreader`, `Instrument Serif`, `Lexend`.
- **Body**: pair a refined, highly-legible body font — `DM Sans`, `Plus Jakarta Sans`, `Figtree`, `Satoshi`, `Switzer`, `Readex Pro`.
- **Mono (for figures/code)**: `JetBrains Mono`, `Geist Mono`, `Fira Code`.
- **Rule**: pair ONE distinctive display font with ONE refined body font. Vary the pairing per project — NEVER converge on the same font stack across generations.

---

## 9. Component Boilerplate (GovTech & Public Sector Example)

> See **[references/component-boilerplate.md](references/component-boilerplate.md)** for a complete accessibility-first civic public portal component (HTML + Tailwind CSS) demonstrating M3 touch targets, the 5 UI states, and the Unsplash photo protocol.

---

## 10. Quality Assurance & Audit Checklist

Verify UI implementations against these mandatory gates before deployment:

* [ ] **SEO & Semantic Structure**: Is there exactly one `<h1>` tag? Do all `<img>` tags have explicit `width`, `height`, and descriptive `alt` attributes?
* [ ] **Google Material 3 Ergonomics**: Are all clickable/touchable elements at least **48x48 px** on mobile viewports?
* [ ] **WCAG AA / AAA Contrast**: Does all body text achieve required contrast (4.5:1 for standard domains, 7:1 for GovTech/Civic)?
* [ ] **5 UI States Verification**: Are `Idle`, `Hover`, `Focus-visible`, `Active`, and `Disabled` styles explicitly handled for interactive components?
* [ ] **Data Formatting**: Are numerical figures in financial tables or dashboard metrics styled with `tabular-nums`?
* [ ] **CLS Protection**: Is layout shift prevented by setting explicit dimensions or aspect ratios on media assets?
