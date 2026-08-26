---
name: pptx
description: "Use this skill whenever a .pptx or .potx presentation file is involved in any way. Triggers include: creating pitch decks, slide decks, or presentations; reading, parsing, or extracting slide content/text; editing or updating existing slides; duplicating or splitting slides; working with PowerPoint templates (.potx), layouts, speaker notes, or comments. Do NOT use for PDFs, spreadsheets (.xlsx), Google Slides, or non-presentation document tasks."
license: MIT
---

# PowerPoint (.pptx / .potx) Skill: Creation, Editing, and Analysis

## 1. Quick Decision Matrix

Determine the operation required before taking action:

| Task / Intent | Method / Tooling | Critical Guardrails |
|---|---|---|
| **Create** new presentation | Write `pptxgenjs` (Node.js) script | Set `pres.layout` BEFORE adding slides. Never use `#` in hex colors. |
| **Edit / Modify** existing deck | `unzip` → edit XML → `zip` | Do **not** use `python-pptx` to duplicate slides or edit SVG/EMF shapes. |
| **Template-based** generation | `scripts/thumbnail.py` + `scripts/add_slide.py` | Always run `clean.py` after deleting or modifying slide references. |
| **Read / Extract** text | `markitdown deck.pptx` | Extract clean markdown with slide number markers (`<!-- Slide number: N -->`). |
| **Convert `.ppt`** | `python scripts/office/soffice.py --headless --convert-to pptx file.ppt` | Legacy binary `.ppt` must be converted to OpenXML `.pptx` first. |

---

## 2. Standard Execution Workflows

### Workflow A: Creating Decks from Scratch (`pptxgenjs`)


```

[Define Layout & Palette] ──> [Write Script (gen.js)] ──> [Run node gen.js] ──> [Validate XML] ──> [Visual QA (PDF/JPG)]

```

1. **Environment Check**: Run `node -e "require('pptxgenjs')"` to confirm availability.
2. **Write Generation Script**: Adhere strictly to the `pptxgenjs` footgun checklist in Section 3.
3. **Execute & Validate**:
   ```bash
   node generate_deck.js
   python scripts/office/validate.py output.pptx

```

4. **Visual Inspection**: Convert to images (see Section 6) and review slide layout.

### Workflow B: Template-Based & XML Editing

```
[Thumbnail Layouts] ──> [Unpack ZIP] ──> [Duplicate Slides] ──> [Edit slideN.xml] ──> [Clean & Repack] ──> [Validate]

```

1. **Select Layouts**:
```bash
python scripts/thumbnail.py template.pptx template-thumbs

```


2. **Unpack & Structure Setup**:
```bash
python3 -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall('unpacked')" template.pptx
python scripts/add_slide.py unpacked/ slide2.xml --after slide2.xml

```


3. **Modify Content & Clean**:
* Edit text/charts inside `unpacked/ppt/slides/slideN.xml` using `defusedxml` or direct string editing.
* Update slide order in `ppt/presentation.xml` (`<p:sldIdLst>`).
* Run cleanup: `python scripts/clean.py unpacked/`


4. **Repack & Validate**:
```bash
(cd unpacked && rm -f ../out.pptx && zip -Xr ../out.pptx .)
python scripts/office/validate.py out.pptx --original template.pptx

```



---

## 3. Essential Technical Standards & Footguns

### Layout & Coordinates

* **Canvas Dimensions**: `LAYOUT_16x9` defaults to **10" × 5.625"**. If widescreen **13.33" × 7.5"** is needed, explicitly set `LAYOUT_WIDE` *before* adding slides:
```js
let pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";

```


* **Text Box Margins**: Text boxes have built-in internal padding. Set `margin: 0` when aligning text boxes flush with shapes, icons, or borders.

### Color & Styling Guardrails (Corruption Prevention)

* [ ] **Hex Format**: Hex colors MUST NOT contain `#` or alpha channels (e.g., use `"FF0000"`, **never** `"#FF0000"` or `"FF0000FF"`).
* [ ] **Transparency**: Use `transparency: 0-100` on fills/images, and `opacity: 0.0-1.0` on shadows.
* [ ] **Option Mutation**: `pptxgenjs` mutates option objects in place. **Never reuse option objects** across multiple `.add*()` calls—construct fresh objects each time.
* [ ] **Shadow Offset**: `offset` must be `≥ 0`. To cast shadows upward, set `angle: 270` with positive offset.
* [ ] **Shape Radius**: `rectRadius` only works on `ROUNDED_RECTANGLE`, not standard `RECTANGLE`.

### Chart Rules (Prevent PowerPoint Crash Errors)

* [ ] **Stacked Chart Labels**: On stacked bar/column charts, `dataLabelPosition` MUST be set to `"ctr"`, `"inEnd"`, or `"inBase"`. Position `"outEnd"` **corrupts the file**.
* [ ] **Combo Charts Dual Axes**: When using `secondaryValAxis` or `secondaryCatAxis`, you MUST declare both `valAxes` and `catAxes` arrays in chart options. Omitting them causes PowerPoint to reject the chart.
* [ ] **Gradients**: `pptxgenjs` does not support gradient fills. Use a high-resolution gradient image background instead.

### Icon & SVG Rendering

To render custom icons reliably:

```js
// Render React Icon to SVG -> Rasterize with Sharp -> Embed Base64 PNG
const iconSvg = ReactDOMServer.renderToStaticMarkup(React.createElement(IconComponent));
const pngBuffer = await sharp(Buffer.from(iconSvg)).resize(512).png().toBuffer();
slide.addImage({ data: "image/png;base64," + pngBuffer.toString("base64"), x: 1, y: 1, w: 0.5, h: 0.5 });

```

---

## 4. Professional Design Standards & Anti-Patterns

### Color Hierarchy & Theme Palettes

* **Visual Weight Ratio**: Follow **60% Primary** (Dominant background/structure), **30% Secondary** (Cards/containers), **10% Accent** (Key stats, focal points).
* **Dark/Light Sandwich**: Use dark backgrounds for Title and Conclusion slides, and light backgrounds for internal content slides.

| Theme Name | Primary (60%) | Secondary (30%) | Accent (10%) |
| --- | --- | --- | --- |
| **Midnight Executive** | `1E2761` (Navy) | `CADCFC` (Ice Blue) | `FFFFFF` (White) |
| **Forest & Moss** | `2C5F2D` (Forest) | `97BC62` (Moss) | `F5F5F5` (Cream) |
| **Warm Terracotta** | `B85042` (Terracotta) | `E7E8D1` (Sand) | `A7BEAE` (Sage) |
| **Teal Trust** | `028090` (Teal) | `00A896` (Seafoam) | `02C39A` (Mint) |

### Typography Guidelines

* **Safe-List Fonts** (100% metric-compatible in QA rendering): `Arial`, `Calibri`, `Cambria`, `Times New Roman`, `Courier New`, `Bookman Old Style`.
* **Font Pairing**: Pair a serif title font (`Cambria`, `Bookman Old Style`) with a sans-serif body font (`Calibri`, `Arial`).
* **Avoid**: Never default to `Aptos` (lacks metric compatibility in headless environments).

### Banned AI Visual Artifacts (STRICT PROHIBITION)

* ❌ **NO Accent Lines Under Titles**: Do not draw decorative horizontal bars beneath slide headers.
* ❌ **NO Border/Edge Stripes**: Do not place colored accent stripes along card edges or full-bleed sidebar stripes down slide borders.
* ❌ **NO Cream/Beige Default Backgrounds**: Use pure white (`FFFFFF`) or topic-driven dark colors unless explicitly requested.
* ❌ **NO Low-Contrast Text**: Ensure high contrast ratios between text and background fills.

---

## 5. Script & Helper Utility Reference

All scripts reside in `scripts/` relative to the skill directory:

* `scripts/thumbnail.py deck.pptx [prefix]` — Generates a multi-page labeled visual grid of template slides.
* `scripts/add_slide.py unpacked/ slideN.xml [--after slideM.xml]` — Safely duplicates slide structures and registers package relationships.
* `scripts/clean.py unpacked/` — Removes orphaned slide files, unreferenced media, and unused relationship references.
* `scripts/office/validate.py deck.pptx [--original src.pptx]` — Runs strict OpenXML validation checks.
* `scripts/office/soffice.py` — Headless LibreOffice wrapper for PDF conversion.

---

## 6. Quality Assurance (QA) & Verification Pipeline

Every generated or modified presentation MUST pass three QA gates before delivery:

### Gate 1: Content & Placeholder QA

```bash
# Verify text content and check for leftover template placeholders
markitdown output.pptx | grep -iE "\bx{3,}\b|lorem|ipsum|\bTODO|\[insert|this.*(page|slide).*layout"

```

*If grep produces output, unresolved placeholders exist.*

### Gate 2: OpenXML Schema & Relationship Validation

```bash
# Standalone deck validation
python scripts/office/validate.py output.pptx

# Template-derived deck validation (baselines against original errors)
python scripts/office/validate.py output.pptx --original template.pptx

```

### Gate 3: Visual Inspection Pipeline

```bash
# Convert presentation to high-resolution JPEG images
python scripts/office/soffice.py --headless --convert-to pdf output.pptx
rm -f slide-*.jpg
pdftoppm -jpeg -r 150 output.pdf slide
ls -1 "$PWD"/slide-*.jpg

```

**Review Generated Slide Images For**:

1. Text overflowing container/slide boundaries.
2. Unintended text wrapping or cramped line heights.
3. Element overlaps (icons covering headers, text clipping shapes).
4. Low-contrast text or icon visibility issues.