# Evidence-Based Design Workflow (Reference → Generate → Verify)

> **Why this matters.** The MCP design tools that people actually pay for
> (Gummble $9/mo, Mobbin, Stitch, 21st.dev) share one loop: they ground the agent
> in *shipped evidence* before it generates, then *verify the rendered output*
> after. An agent that designs from guesses produces "AI slop". An agent that
> designs from evidence produces work that reads as professionally shipped.
>
> This reference encodes that loop so our skill produces the same quality
> without any paid MCP.

---

## The Three-Stage Loop

```
1. REFERENCE   →  ground the design in shipped patterns & real copy
2. GENERATE    →  produce modular, token-driven, shadcn-convention components
3. VERIFY      →  render it, screenshot it, and check it against the QA gates
```

Never skip a stage. Skipping **REFERENCE** produces generic layouts. Skipping
**VERIFY** ships broken or inaccessible UI.

---

## Stage 1 — REFERENCE (design with evidence, not guesses)

Before writing a single line, anchor the design in what real products ship:

1. **Domain vernacular** — consult `domain-archetypes.md` for the color token
   strategy, typography stack, and signature layout element of the target domain.
2. **Real microcopy** — consult `microcopy-patterns.md` for empty states, errors,
   onboarding, and paywall copy. Never invent placeholder text.
3. **Shipped patterns** — for any component (hero, pricing, nav, empty state),
   recall 1–2 real shipped examples and note *why* they work before adapting.
4. **One bold choice** — commit to a single justifiable aesthetic direction
   (a distinctive display font, an unusual accent color, a signature layout).
   Never hedge with "safe" defaults.

**Output of this stage:** a short design brief (3–5 bullets) stating the domain,
the token strategy, the typography pairing, the one bold choice, and the microcopy
tone. If you can't write this brief, you're not ready to generate.

---

## Stage 2 — GENERATE (modular, token-driven, shadcn-convention)

Generate components the way 21st.dev and shadcn MCP do — as **self-contained,
composable modules** wired to design tokens, not monolithic pages.

### Component structure rules

- **One component per file.** `hero.tsx`, `pricing.tsx`, `empty-state.tsx`,
  `button.tsx`. Never one giant `page.tsx` with everything inline.
- **Token-driven styling.** Reference CSS variables (`var(--brand-accent)`), never
  hardcode hex values inside components. Tokens live once in `:root`.
- **shadcn/ui conventions.** Use `cn()` / `clsx` for conditional classes, `cva`
  for variants, and a `components/ui/` folder for primitives. Compose primitives
  into sections.
- **Variants over one-offs.** Buttons, badges, cards should expose variants
  (`variant="primary" | "secondary" | "ghost"`) rather than being copy-pasted
  with tweaked classes.
- **Real copy inline.** Every string uses the microcopy from Stage 1. No lorem.

### Example: a token-driven button (shadcn convention)

```tsx
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex h-12 items-center justify-center rounded-lg px-6 text-sm font-semibold transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed",
  {
    variants: {
      variant: {
        primary: "bg-[var(--brand-accent)] text-white hover:bg-[var(--brand-accent-hover)]",
        secondary: "border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--text-primary)] hover:bg-[var(--bg-surface-elevated)]",
        ghost: "text-[var(--text-muted)] hover:bg-[var(--bg-surface)]",
      },
    },
    defaultVariants: { variant: "primary" },
  }
);

export function Button({ className, variant, ...props }: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants>) {
  return <button className={cn(buttonVariants({ variant }), className)} {...props} />;
}
```

**Output of this stage:** modular components + a page that composes them, all
wired to tokens, all with real microcopy.

---

## Stage 3 — VERIFY (render, screenshot, audit)

An agent that never sees its own output ships broken UI. Verify before declaring
done:

1. **Render it** — open the page in a real browser (Playwright MCP / Chrome
   DevTools MCP pattern). If no browser is available, at minimum validate the
   markup and CSS.
2. **Screenshot at multiple viewports** — mobile (375px), tablet (768px), desktop
   (1280px). Check for overflow, clipped text, broken layout.
3. **Run the QA gates** from `SKILL.md` §9:
   - Exactly one `<h1>`; heading order correct.
   - All `<img>` have `width`, `height`, `alt`.
   - Touch targets ≥ 48×48 on mobile.
   - Contrast ≥ 4.5:1 (7:1 for GovTech).
   - All 5 UI states (idle/hover/focus/active/disabled) present.
   - `tabular-nums` on figures; explicit dimensions to prevent CLS.
4. **Fix and re-verify.** Verification is a loop, not a checkbox.

**Output of this stage:** a verified page + a short note of what was checked and
what was fixed.

---

## Why this loop beats "just generate"

| Without the loop | With the loop |
|---|---|
| Generic purple-gradient hero, Inter font | Domain-grounded tokens, characterful type |
| "Fast. Reliable. Secure." | Real microcopy with a next action |
| Monolithic page, hardcoded colors | Modular token-driven components |
| Ships unseen, broken at 375px | Rendered + screenshot-verified |
| Reads as AI-generated | Reads as professionally shipped |

This is the exact value proposition the paid design MCPs sell — encoded here as a
free, repeatable workflow.
