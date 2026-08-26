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

## 2. Unsplash Visual Assets Protocol

Use authentic, high-resolution photography from Unsplash for realistic mockups. Never use gray placeholder boxes.

> See **[references/unsplash-assets.md](references/unsplash-assets.md)** for the URL construction rule and the curated photo ID directory by domain.

---

## 3. Google Design (Material 3 Ergonomics) & Accessibility (WCAG 2.1)

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

## 4. Technical SEO & Core Web Vitals Standards

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

## 5. System Tokens & CSS Variable Boilerplate

Include these standard tokens in CSS configurations for full cross-component theme consistency:

```css
:root {
  /* Color Tokens */
  --bg-base: #0f172a;
  --bg-surface: #1e293b;
  --bg-surface-elevated: #334155;
  --text-primary: #f8fafc;
  --text-muted: #94a3b8;
  --border-subtle: rgba(255, 255, 255, 0.1);
  --brand-accent: #2563eb;
  --brand-accent-hover: #1d4ed8;

  /* Typography & Layout Tokens */
  --font-display: 'Clash Display', 'Playfair Display', sans-serif;
  --font-body: 'Inter', system-ui, -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;
  --radius-card: 1rem;
  --radius-button: 0.5rem;

  /* Motion Tokens */
  --transition-fast: 150ms cubic-bezier(0.16, 1, 0.3, 1);
  --transition-normal: 300ms cubic-bezier(0.16, 1, 0.3, 1);
}

.dark {
  --bg-base: #09090b;
  --bg-surface: #18181b;
  --text-primary: #fafafa;
  --border-subtle: rgba(255, 255, 255, 0.08);
}
```

---

## 6. Component Boilerplate (GovTech & Public Sector Example)

> See **[references/component-boilerplate.md](references/component-boilerplate.md)** for a complete accessibility-first civic public portal component (HTML + Tailwind CSS) demonstrating M3 touch targets, the 5 UI states, and the Unsplash photo protocol.

---

## 7. Quality Assurance & Audit Checklist

Verify UI implementations against these mandatory gates before deployment:

* [ ] **SEO & Semantic Structure**: Is there exactly one `<h1>` tag? Do all `<img>` tags have explicit `width`, `height`, and descriptive `alt` attributes?
* [ ] **Google Material 3 Ergonomics**: Are all clickable/touchable elements at least **48x48 px** on mobile viewports?
* [ ] **WCAG AA / AAA Contrast**: Does all body text achieve required contrast (4.5:1 for standard domains, 7:1 for GovTech/Civic)?
* [ ] **5 UI States Verification**: Are `Idle`, `Hover`, `Focus-visible`, `Active`, and `Disabled` styles explicitly handled for interactive components?
* [ ] **Data Formatting**: Are numerical figures in financial tables or dashboard metrics styled with `tabular-nums`?
* [ ] **CLS Protection**: Is layout shift prevented by setting explicit dimensions or aspect ratios on media assets?
