# UX Philosophy & Laws (Self-Contained, Priority-Ordered)

> **Why this matters.** The best UI/UX skills for AI agents (ui-ux-laws, UXPeak,
> design-principles) share one core idea: a great interface is not a collection of pretty
> components — it is a set of **constraints the model enforces on its own output**, ordered
> by priority so trade-offs are explicit. A gorgeous interface that fails clarity is a
> failed interface.
>
> This reference encodes those laws as **actionable rules** (not trivia), fully
> self-contained — no external MCP or API required. When two rules conflict, the Priority
> Hierarchy below decides which wins.

---

## 1. Priority Hierarchy (the tie-breaker)

When rules pull in different directions, resolve in this order. Never let aesthetics beat
clarity or accessibility.

> **Accessibility & safety → clarity & findability → correctness & forgiveness →
> efficiency of effort → consistency → aesthetic polish.**

- **Accessibility & safety** — contrast, keyboard, focus, target size, motion, no
  misleading destructive actions.
- **Clarity & findability** — can the user see what to do and where it is?
- **Correctness & forgiveness** — right data, undoable mistakes, recovery paths.
- **Efficiency of effort** — fewest clicks/keystrokes to complete the task.
- **Consistency** — same pattern = same meaning across the product.
- **Aesthetic polish** — the last priority, never the first.

**Apply:** when a design choice is pretty but hurts findability, drop the pretty and fix
the findability.

---

## 2. Nielsen's 10 Usability Heuristics (fast checklist)

1. **Visibility of system status** — always show what's happening (loading, progress, saved).
2. **Match between system and real world** — speak the user's language, familiar metaphors.
3. **User control and freedom** — emergency exit, undo, cancel (e.g. `Ctrl+Z`, "Back").
4. **Consistency and standards** — same icon/word = same action everywhere.
5. **Error prevention** — prevent errors before they happen (confirm destructive, disable invalid).
6. **Recognition rather than recall** — show options; don't make user memorize.
7. **Flexibility and efficiency of use** — accelerators, defaults, shortcuts for power users.
8. **Aesthetic and minimalist design** — every unit of info competes for attention; cut noise.
9. **Help users recognize, diagnose, and recover from errors** — error says *what + why + how*.
10. **Help and documentation** — searchable, task-focused help when needed.

**Apply:** run this as a silent checklist on every finished screen before declaring done.

---

## 3. Gestalt Principles (perception → grouping)

These govern how users *see* relationships between elements before they read anything:

- **Proximity** — elements close together are perceived as one group. Use spacing to group
  related controls; don't rely on borders alone.
- **Similarity** — elements that look alike (color, shape, size) are perceived as related.
  Same style = same function.
- **Common region** — elements inside a shared container (card, panel) are grouped.
- **Continuity** — the eye follows lines/curves; align elements so flow is uninterrupted.
- **Closure** — the mind fills in gaps; a partially drawn shape reads as complete.
- **Figure/ground** — the focal element must clearly separate from its background (contrast,
  shadow, tonal shift).

**Apply:** use proximity & common region to build hierarchy without adding more borders;
use similarity to signal "these buttons do the same kind of thing".

---

## 4. Cognitive Psychology & UX Laws

- **Hick's Law** — decision time grows with number & complexity of choices. Reduce options;
  use safe defaults; progressive disclosure for advanced choices.
- **Fitts's Law** — time to reach a target depends on its size and distance. Make primary
  actions large and near the thumb/cursor; keep destructive actions far and small.
- **Miller's Law / cognitive load** — working memory holds ~7±2 chunks. Chunk information;
  don't dump everything at once.
- **Recognition over recall** — show available options rather than requiring memory (ties to
  Nielsen #6).
- **Serial position effect** — users remember first & last items best. Put the most important
  action at the start or end of a list/flow.
- **Anchoring** — the first number shown biases judgment. In pricing, show the value anchor
  before the price.
- **Progressive disclosure** — reveal advanced/complex options only when needed to reduce
  initial load.

**Apply:** for any flow, ask "what's the minimum the user must decide right now?" and hide
the rest until it's relevant.

---

## 5. Ethical Guardrails (dark patterns — NEVER ship)

An explicit "don't" list. These destroy trust and read as manipulative:

- **Hidden costs** — reveal full price (incl. fees) before commitment.
- **Manufactured urgency** — fake countdowns, fake "only 2 left".
- **Forced action** — tricking the user into subscribing/opt-in they didn't intend.
- **Obscured cancellation** — make cancel/unsubscribe as easy as signup.
- **Roach motel** — easy to enter, hard to leave.
- **Confirmshaming** — guilt-tripping copy ("No thanks, I don't care about my health").
- **Misleading defaults** — pre-checked boxes for things the user didn't ask for.

**Apply:** if a pattern manipulates rather than informs, it is out. Accessibility & informed
choice always beat conversion tricks.

---

## 6. Accessibility Non-Negotiables (RTL-aware)

Beyond contrast (§4 of SKILL.md):

- **Keyboard** — every interactive element reachable & operable by keyboard; visible focus
  (`focus-visible:ring-2`).
- **Target size** — ≥ 48×48 px mobile, ≥ 40×40 px desktop.
- **RTL / LTR mirroring** — for Persian/Arabic/Hebrew, *mirror the whole layout*, not just
  right-align text. Flip directional icons (back arrow, progress, chevrons). Reserve ~30%
  extra horizontal space for languages that expand when translated (German, Finnish).
- **Motion** — respect `prefers-reduced-motion`; don't auto-play or flash.
- **Labels** — every input has a visible label; icon-only buttons have `aria-label`.

**Apply:** treat RTL as a first-class layout mode, not a text alignment afterthought.

---

## 7. Component Quick-Reference (which laws matter most)

| Component | Laws that matter most |
|---|---|
| **Forms** | Error prevention, recognition over recall, labels, Hick's law (fewer fields), recovery |
| **Navigation** | Consistency, findability, Fitts's law (big targets), serial position (first/last) |
| **Modals** | User control (escape/close), focus trap, visibility of status, progressive disclosure |
| **Tables / data** | Recognition, consistency, tabular-nums, anchoring (totals first) |
| **Empty states** | Visibility, help & documentation, microcopy with a next action |
| **Pricing** | Anchoring, hidden-cost ban, value before commitment, clarity |
| **Onboarding** | Progressive disclosure, cognitive load, recognition, serial position |
| **Paywall** | Value before commitment, transparency, no fake urgency |

---

## 8. Design Stance & Working Workflow (UXPeak)

**Begin with the user, task, context, and business outcome** — not with the visual. Treat UX
and UI as one loop: understand users → frame the problem → explore flows → prototype → test →
refine → hand off an implementable system.

1. **Frame the job** — audience, user goal, stage in journey, device/environment, success
   metric, constraints. State assumptions when research is unavailable.
2. **Diagnose** — first-scan hierarchy, content relevance, interaction cost, information
   architecture, states & feedback, trust signals, accessibility, responsiveness, consistency.
3. **Simplify the decision** — remove redundant choices, expose useful content, safe
   defaults, match controls to the task, keep the main action near the info needed.
4. **Add useful context** — status, progress, totals, timing, consequences, examples,
   recovery paths at the moment they reduce hesitation.
5. **Polish the system** — coherent grid, type scale, color roles, icon style, spacing,
   component states, restrained motion. Make hierarchy survive real content & screen sizes.
6. **Validate** — propose usability/A-B tests for consequential hypotheses; separate
   observed evidence from expectation; never promise a conversion lift without measurement.
7. **Handoff** — document responsive behavior, dimensions, spacing, states, interactions,
   content rules, accessibility, component/token dependencies.

---

## 9. Visual-Rationale Requirement ("what not to do")

For redesigns or reference-driven work, include a **"what not to do" pass**. Name every
meaningful alternative, explain what works, what fails and why, and extract a transferable
decision rule. Format: **option → user effect → failure or benefit → decision rule**.

Check for:
- alternatives that look attractive alone but fail in the surrounding system;
- weak focal points, misleading imagery, unreadable overlays, inconsistent assets;
- hierarchy that emphasizes labels/decoration over the user's actual answer;
- controls that add reach, typing, scanning, precision, or decision burden;
- hidden value, hidden cost, missing status, missing totals, ambiguous consequences;
- visual novelty that breaks familiar behavior, accessibility, performance, or motion comfort.

Never call a choice "better" without saying what the rejected alternatives get wrong and why
the choice should work for the stated user and context.

---

## 10. Response Shape

- **Critique**: context & assumptions → what works → highest-impact frictions (priority
  order) → specific recommendation each → rationale tied to user goal → validation plan.
- **Redesign / new flow**: user state → primary job → information & action hierarchy → key
  states & edge cases → interaction & copy behavior → visual system requirements →
  responsive/accessibility requirements → what to test first.
- **Implementation guidance**: translate into components, tokens, states, content rules,
  acceptance criteria — not just appearance.
