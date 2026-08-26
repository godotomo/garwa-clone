---
name: pdf
description: "Use this skill whenever a PDF file is the primary input, modification target, or generation deliverable. Triggers include reading, extracting text/tables, merging, splitting, rotating, encrypting, filling forms, OCR on scanned docs, and creating stylized PDFs with diverse layouts and design themes. Output MUST be a PDF file or extracted structured data."
license: MIT
---

# PDF Processing, Design & Layout Engine

## Tool Selection Matrix

| Task / Requirement | Recommended Engine | Alternative / CLI |
|---|---|---|
| **Text & Table Extraction** | `pdfplumber` | `pdftotext` (poppler-utils) |
| **Merge / Split / Rotate / Encrypt** | `pypdf` | `qpdf` / `pdftk` |
| **Stylized PDF Generation & Layouts** | `reportlab` (Platypus) | `weasyprint` (HTML to PDF) |
| **Scanned Document OCR** | `pytesseract` + `pdf2image` | `tesseract` CLI |
| **Image Extraction** | `pypdfium2` / `pdfimages` | `pdfplumber` |
| **PDF Form Filling & Stamping** | `pypdf` / `pdf-lib` | `pdftk` |

---

## 1. Design & Layout Engine (`reportlab`)

### A. Theme Palette System

Gunakan palet warna terstruktur untuk menghasilkan dokumen bergaya profesional.

| Theme Name | Primary Accent | Secondary / Surface | Body Text | Target Use Case |
|---|---|---|---|---|
| **Corporate Navy** | `#1E3A8A` (Dark Blue) | `#F1F5F9` (Slate Light) | `#1E293B` | Financial Reports, Pitch Decks |
| **Minimalist Dark** | `#0F172A` (Slate Dark) | `#6366F1` (Indigo Accent) | `#E2E8F0` | Modern Tech Guides, API Specs |
| **Academic Maroon**| `#7F1D1D` (Deep Red) | `#FDF2F2` (Soft Crimson) | `#111827` | Academic Papers, Contracts |
| **Modern Eco** | `#065F46` (Forest Green) | `#ECFDF5` (Mint Tint) | `#064E3B` | Sustainability, Certificates |

---

### B. Layout Frameworks

#### 1. Header, Footer, & Page Numbering Engine
Gunakan `BaseDocTemplate` dan `PageTemplate` untuk halaman multi-halaman berulang (Header, Footer, Dynamic Page Count).

```python
from reportlab.lib.pagesizes import letter
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def draw_header_footer(canvas, doc):
    canvas.saveState()
    # Header Line & Label
    canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
    canvas.line(54, 738, 558, 738)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(54, 745, "EXECUTIVE SUMMARY & REPORT")
    
    # Footer Page Number
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(558, 36, f"Page {doc.page}")
    canvas.restoreState()

# Setup Document Structure (0.75-inch margins = 54pt)
doc = BaseDocTemplate("report_output.pdf", pagesize=letter)
frame = Frame(54, 54, 504, 684, id='main_frame')
template = PageTemplate(id='HeaderFooter', frames=frame, onPage=draw_header_footer)
doc.addPageTemplates([template])

```

#### 2. Multi-Column Tables & Invoices

Gunakan `Table` dan `TableStyle` untuk tata letak berbasis kisi (*grid*).

```python
from reportlab.platypus import Table, TableStyle

data = [
    ["Item Description", "Qty", "Unit Price", "Total"],
    ["Cloud Infrastructure Setup", "1", "$1,200.00", "$1,200.00"],
    ["Database Optimization & Tuning", "5 hrs", "$150.00", "$750.00"]
]

table_style = TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1E3A8A")),
    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
    ('FONTSIZE', (0,0), (-1,0), 9),
    ('BOTTOMPADDING', (0,0), (-1,0), 6),
    ('BACKGROUND', (0,1), (-1,-1), colors.HexColor("#F8FAFC")),
    ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
    ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
])

invoice_table = Table(data, colWidths=[240, 60, 100, 104], style=table_style)

```

---

## 2. Core Python Operations

### A. Extraction (Text & Tables)

```python
import pdfplumber
import pandas as pd

# Extract Text with Layout
with pdfplumber.open("document.pdf") as pdf:
    full_text = "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])

# Extract Tables to Excel/CSV
with pdfplumber.open("tables.pdf") as pdf:
    all_dfs = []
    for page in pdf.pages:
        for table in page.extract_tables():
            if table and len(table) > 1:
                df = pd.DataFrame(table[1:], columns=table[0])
                all_dfs.append(df)
    if all_dfs:
        pd.concat(all_dfs, ignore_index=True).to_csv("output.csv", index=False)

```

### B. Manipulation (Merge, Split, Rotate, Encrypt)

```python
from pypdf import PdfReader, PdfWriter

# Merge PDFs
def merge_pdfs(pdf_list, output_path):
    writer = PdfWriter()
    for file in pdf_list:
        reader = PdfReader(file)
        for page in reader.pages:
            writer.add_page(page)
    with open(output_path, "wb") as f:
        writer.write(f)

# Encrypt PDF
def encrypt_pdf(input_path, output_path, password):
    reader = PdfReader(input_path)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(user_password=password, owner_password=password)
    with open(output_path, "wb") as f:
        writer.write(f)

```

### C. Scanned Document OCR

```python
import pytesseract
from pdf2image import convert_from_path

def ocr_pdf(pdf_path):
    images = convert_from_path(pdf_path)
    ocr_text = ""
    for i, img in enumerate(images):
        ocr_text += f"--- Page {i+1} ---\n"
        ocr_text += pytesseract.image_to_string(img) + "\n\n"
    return ocr_text

```

---

## 3. Command-Line (CLI) Cheatsheet

```bash
# Extract raw text with preserved layout
pdftotext -layout input.pdf output.txt

# Merge PDFs via qpdf
qpdf --empty --pages file1.pdf file2.pdf -- merged.pdf

# Split PDF pages 1-5
qpdf input.pdf --pages . 1-5 -- pages1-5.pdf

# Rotate page 1 by 90 degrees clockwise
qpdf input.pdf output.pdf --rotate=+90:1

# Extract images from PDF
pdfimages -j input.pdf image_prefix

# Fill PDF Form (using pdftk if available)
pdftk form.pdf fill_form data.fdf output filled.pdf flatten

```

---

## 4. Master Quick Reference

| Task | Best Tool / Library | Key Function / Command |
| --- | --- | --- |
| **Merge PDFs** | `pypdf` / `qpdf` | `writer.add_page(page)` / `qpdf --empty --pages` |
| **Split PDF Pages** | `pypdf` / `qpdf` | Iterate `reader.pages` / `qpdf input.pdf --pages . 1-5` |
| **Rotate Pages** | `pypdf` | `page.rotate(90)` |
| **Extract Text** | `pdfplumber` | `page.extract_text()` |
| **Extract Tables** | `pdfplumber` + `pandas` | `page.extract_tables()` |
| **Extract Images** | `poppler-utils` | CLI: `pdfimages -j input.pdf img_prefix` |
| **OCR Scanned Docs** | `pytesseract` + `pdf2image` | `pytesseract.image_to_string(image)` |
| **Create Custom PDFs** | `reportlab` (Platypus) | `SimpleDocTemplate` / `BaseDocTemplate` |
| **Fill Forms** | `pypdf` / `pdftk` | `writer.update_page_form_field_values()` |
| **Encrypt / Decrypt** | `pypdf` / `qpdf` | `writer.encrypt("pass")` / `qpdf --decrypt` |

---

## 5. Critical Technical Gotchas

1. **Subscript & Superscript Formatting:**
* **DO NOT** use Unicode subscript/superscript characters (`₂`, `³`). Standard ReportLab fonts will render them as black boxes.
* **MUST USE** HTML-like markup inside `Paragraph`: `<sub>2</sub>` or `<super>2</super>`.


2. **Standard Built-in Fonts:**
* Stick to `Helvetica`, `Times-Roman`, and `Courier`. External TTF files require explicit registration via `reportlab.pdfbase.ttfonts`.


3. **Execution Completion:**
* Always call `doc.build(story)` (Platypus) or `canvas.save()` (Canvas API) to write the PDF binary to disk; omitting this causes empty 0-byte files.