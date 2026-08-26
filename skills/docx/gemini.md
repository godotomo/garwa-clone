---
name: docx
description: "Use this skill whenever the user asks to create, read, edit, analyze, or manipulate Word documents (.docx, .dotx) or legacy Word files (.doc). Triggers include requests for reports, letters, memos, proposals, forms, templates, or redlining/track changes in Word format. Covers document generation with advanced formatting (TOC, page numbers, tables, callouts, letterheads), text extraction, find-and-replace, commenting, and redlining. Do NOT use for PDFs, Google Docs, spreadsheets (.xlsx), or general non-document programming tasks."
license: MIT
---

# Word Document (.docx) Skill: Creation, Editing, and Analysis

## 1. Quick Decision Matrix

Determine the operation required before taking action:

| Task / Intent | Method / Tooling | Critical Guardrails |
|---|---|---|
| **Create** new file | `docx` (npm / Node.js) | Do NOT `npm install` unless `require('docx')` fails. Use DXA units for layout. |
| **Edit / Redline** existing | Unpack `.docx` → Modify XML → Pack | **Never** use `docx-js` to open existing files (it cannot parse `.docx`). |
| **Read / Analyze** | `pandoc -t markdown input.docx` | Fast text extraction without breaking archive structure. |
| **Convert `.doc`** | `python scripts/office/soffice.py --headless --convert-to docx file.doc` | Convert legacy binary files to XML format first. |

---

## 2. Standard Execution Workflows

### Workflow A: Creating New Documents (`docx-js`)


```

[Define Rules/Layout] ──> [Write Script (script.js)] ──> [Run node script.js] ──> [Verify via PDF/Images]

```

1. **Environment Check**: Run `node -e "require('docx')"` to confirm availability.
2. **Write Generation Script**: Generate Node.js script adhering strictly to API footgun rules below.
3. **Execute & Render Verification**:
   ```bash
   node generate_doc.js
   python scripts/office/soffice.py --headless --convert-to pdf output.docx
   pdftoppm -jpeg -r 100 output.pdf page

```

4. **Visual QC**: Inspect generated `page-*.jpg` images before finalizing.

### Workflow B: Editing & Redlining Existing Documents

```
[Convert .doc if needed] ──> [Unpack ZIP] ──> [Sanitize & Merge Runs] ──> [Edit XML] ──> [Validate] ──> [Repack]

```

1. **Unpack Safely**:
```bash
unzip -q contract.docx -d unpacked/
find unpacked -type l -delete # Remove untrusted symlinks

```


2. **Merge Fragmented Runs** (Crucial for finding text):
```bash
python scripts/merge_runs.py unpacked/

```


3. **Modify `word/document.xml**`: Perform direct string replacement or XML modification (do **not** reformat/indent XML).
4. **Validate & Repack**:
```bash
(cd unpacked && rm -f ../out.docx && zip -Xr ../out.docx .)
python scripts/office/validate.py out.docx --original contract.docx

```


5. *(Optional)* **Accept Changes**: To generate a clean final copy:
```bash
python scripts/accept_changes.py out.docx clean_final.docx

```



---

## 3. Essential Technical Standards & Footguns

### Layout & Page Geometry (DXA Scale)

* **Unit Rules**: 1 inch = 72 pt = 1440 DXA. 1 pt = 20 DXA.
* **Standard Page Dimensions**:
* **US Letter**: `width: 12240`, `height: 15840`
* **A4**: `width: 11906`, `height: 16838`


* **Landscape Orientation**: Keep portrait dimensions in `size`, but add `orientation: PageOrientation.LANDSCAPE`. `docx-js` will handle axis swapping automatically.

### Table Construction Checklist

* [ ] **Dual Widths**: Always set `columnWidths` on `Table` AND explicit `width` on every `TableCell` using `WidthType.DXA`. (Do **not** use `PERCENTAGE`; it breaks in Google Docs and LibreOffice).
* [ ] **Column Sum**: Total of `columnWidths` must equal total section width minus margins.
* [ ] **Cell Shading**: Use `ShadingType.CLEAR` with fill color hex code. **Never** use `ShadingType.SOLID` (causes pure black fill in Word).
* [ ] **Cell Padding**: Explicitly set top, bottom, left, right cell margins in DXA.

### Typography & Content Rules

* [ ] **No Raw Newlines**: Do not use `\n` inside `TextRun`. Break text into multiple `Paragraph` objects or use `new TextRun({ break: 1 })`.
* [ ] **Bullet / Numbered Lists**: Do not write literal `•` characters. Use `bullet: { level: 0 }` or `numbering` references.
* [ ] **Horizontal Rules**: Do not use empty tables. Use paragraph bottom border (`border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "CCCCCC" } }`).
* [ ] **Right Alignment / Dot Leaders**: Use `PositionalTab` with `alignment: PositionalTabAlignment.RIGHT` and `leader: PositionalTabLeader.DOT`.
* [ ] **Images**: Always specify `type` parameter inside `ImageRun` (e.g., `type: "png"` or `type: "jpg"`).
* [ ] **Page Breaks**: `PageBreak` element must reside *inside* a `Paragraph`.

---

## 4. XML Manipulation Reference (Redlining & Comments)

### Tracked Changes Schema Syntax

When inserting modifications directly in XML (`word/document.xml`):

* **Inserted Text**:
```xml
<w:ins w:id="1" w:author="AI Assistant" w:date="2026-08-19T10:00:00Z">
  <w:r><w:t>Inserted text here</w:t></w:r>
</w:ins>

```


* **Deleted Text**:
```xml
<w:del w:id="2" w:author="AI Assistant" w:date="2026-08-19T10:00:00Z">
  <w:r><w:delText>Deleted text here</w:delText></w:r>
</w:del>

```


* **Schema Order Requirement**: Inside `<w:pPr>`, `<w:del>` or `<w:rPr>` must precede other formatting properties. Order matters!

### Adding Comments via Helper Script

Do not write 6 cross-linked comment XML files manually. Use the built-in script:

```bash
# Directory Mode (Unpacked)
python scripts/comment.py unpacked/ "Comment text here" --author "Reviewer"

# Single-file Mode
python scripts/comment.py input.docx "Comment text here" -o annotated.docx

```

*Note: Copy the printed `<w:commentRangeStart>`, `<w:commentRangeEnd>`, and `<w:commentReference>` tags into `word/document.xml` to anchor the comment.*

---

## 5. Dependencies & Environment

* **Core Libraries**: `docx` (npm), `pandoc`, LibreOffice (`soffice`), Poppler utilities (`pdftoppm`).
* **Python Helpers**:
* `scripts/office/soffice.py` (Headless PDF conversion)
* `scripts/merge_runs.py` (Run normalization)
* `scripts/office/validate.py` (XSD OpenXML validation)
* `scripts/comment.py` (Comment generator)
* `scripts/accept_changes.py` (Track changes flattener)