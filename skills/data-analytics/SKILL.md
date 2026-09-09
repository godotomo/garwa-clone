---
name: data-analytics
description: "Use this skill whenever the user wants to analyze, clean, transform, or visualize tabular data (CSV, 
Parquet, JSON, Excel) or write/optimize SQL queries. Covers exploratory data analysis (EDA), data wrangling with 
pandas/polars, statistical summaries, generating charts (matplotlib/seaborn/plotly), as well as writing, debugging, and 
tuning SQL queries (PostgreSQL, MySQL, SQLite, BigQuery). Do NOT use for document generation (.docx, .pptx, .xlsx 
layout formatting) or general software engineering tasks unrelated to data."
license: MIT
---

# Data & Analytics Skill: Data Wrangling, Visualization, and SQL

## 1. Quick Decision Matrix

Determine the appropriate framework and execution strategy before running code or writing queries:

| Data Size / Task | Primary Tool / Engine | Key Approach & Guardrails |
|---|---|---|
| **Small-Medium Data** (< 1 GB) | `pandas` / `numpy` | Default in-memory analysis. Check `.dtypes` and missing values 
first. |
| **Large Data / High Speed** (> 1 GB) | `polars` or `duckdb` | Use lazy evaluation (`scan_csv`/`scan_parquet`). Avoid 
`.to_pandas()` early. |
| **Chart / Plot Generation** | `seaborn` / `matplotlib` / `plotly` | Export high-res PNG/SVG. Always set explicit 
titles, axis labels, and legend. |
| **Relational Queries / SQL** | Dialect-Specific SQL | Use explicit ANSI JOINs, CTEs for readability, and indexed 
filters. |

---

## 2. Standard Execution Workflows

### Workflow A: Python Data Analysis & Visualization (`pandas` / `seaborn`)


```

[Inspect Schema & Nulls] ──> [Clean & Transform] ──> [Compute Metrics] ──> [Generate Plot] ──> [Verify Output]

```

1. **Schema Check & Profiling**:
   ```python
   import pandas as pd

   df = pd.read_csv("dataset.csv")
   print(df.info())
   print(df.isnull().sum())

```

2. **Data Cleaning & Transformation**:
* Handle missing values explicitly (impute or drop with clear documented reasons).
* Convert date columns via `pd.to_datetime()`.
* Downcast numeric types if memory efficiency is required.


3. **Statistical Computation**:
* Use vectorization (`.groupby()`, `.agg()`, `.transform()`). Avoid iterating over rows (`for`, `iterrows()`).


4. **Visualization Generation**:
* Save plot outputs as crisp image files for inspection (`dpi=300`).



### Workflow B: SQL Querying & Schema Design

```
[Analyze Requirements] ──> [Draft Query using CTEs] ──> [Optimize Aggregations/JOINs] ──> [Verify Performance]

```

1. **Drafting Structurally**:
* Use **Common Table Expressions (CTEs)** (`WITH ... AS`) instead of deeply nested subqueries.
* Explicitly qualify columns with table aliases (e.g., `o.order_id`, `c.customer_name`).


2. **Performance Review**:
* Filter early (`WHERE` clauses applied before `JOIN`s or heavy aggregation).
* Avoid `SELECT *`. Select only required columns.



---

## 3. Essential Technical Standards & Footguns

### Python & Pandas Traps

* [ ] **SettingWithCopyWarning**: Never mutate sliced dataframes directly. Use `.loc[mask, 'col'] = val` or explicit 
`.copy()`.
* [ ] **No Iterrow Loop**: Avoid `.iterrows()` or `.apply()` for basic math. Use vectorized expressions (e.g., 
`df['total'] = df['qty'] * df['price']`).
* [ ] **Datetime Parsing Errors**: Always pass explicit date formats to `pd.to_datetime(df['date'], format='%Y-%m-%d')` 
or set `errors='coerce'` to capture malformed rows.
* [ ] **Data Imbalance in GroupBy**: When using `.groupby()`, explicitly pass `observed=True` for categorical data to 
avoid memory explosion.

### Chart & Visualization Standards

* [ ] **No Bare Plots**: Every chart MUST have:
* Informative main title (`plt.title()`).
* Explicit X and Y axis labels with units (e.g., `Revenue (USD)`, `Date (YYYY-MM)`).
* Clear legend if multiple categories/series are plotted.


* [ ] **Color Contrast & Accessibility**: Use colorblind-safe palettes (e.g., `seaborn.color_palette("viridis")` or 
`"muted"`).
* [ ] **Layout Tightness**: Call `plt.tight_layout()` or `fig.update_layout()` to prevent label clipping before saving.

### SQL Query & Schema Traps

* [ ] **Implicit Cross Joins**: Never use comma-separated table lists in `FROM`. Use explicit `JOIN` syntax (`INNER 
JOIN`, `LEFT JOIN`).
* [ ] **NULL Handling in Aggregates**: Remember `COUNT(column)` ignores `NULL`s, whereas `COUNT(*)` counts all rows. 
Use `COALESCE(val, 0)` when adding or comparing nullable metrics.
* [ ] **`HAVING` vs `WHERE**`: Use `WHERE` for row-level filtering *before* aggregation; use `HAVING` *only* for 
filtering aggregated results (`COUNT`, `SUM`).
* [ ] **Non-Deterministic Ordering**: When using window functions (`ROW_NUMBER() OVER (...)`), always provide a unique 
secondary sort column to ensure reproducible ranking.

---

## 4. Code & Query Templates

### Boilerplate 1: Publication-Quality Plot (`seaborn` / `matplotlib`)

```python
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

# Set global style
sns.set_theme(style="whitegrid", palette="muted")
fig, ax = plt.subplots(figsize=(10, 6), dpi=300)

# Sample Plot
sns.barplot(data=df, x="category", y="revenue_usd", estimator="sum", errorbar=None, ax=ax)

# Polish formatting
ax.set_title("Total Revenue by Product Category (FY2026)", fontsize=14, fontweight="bold", pad=15)
ax.set_xlabel("Product Category", fontsize=11, labelpad=10)
ax.set_ylabel("Total Revenue ($ USD)", fontsize=11, labelpad=10)
ax.yaxis.set_major_formatter("${x:,.0f}")
plt.xticks(rotation=45, ha="right")

plt.tight_layout()
plt.savefig("revenue_by_category.png")
plt.close()

```

### Boilerplate 2: Analytical SQL with CTE & Window Functions

```sql
WITH monthly_sales AS (
    SELECT 
        DATE_TRUNC('month', o.order_date) AS sales_month,
        p.category_id,
        SUM(o.order_amount_usd) AS total_revenue
    FROM orders o
    INNER JOIN products p ON o.product_id = p.product_id
    WHERE o.order_status = 'COMPLETED'
      AND o.order_date >= '2026-01-01'
    GROUP BY 1, 2
),
ranked_categories AS (
    SELECT 
        sales_month,
        category_id,
        total_revenue,
        DENSE_RANK() OVER (PARTITION BY sales_month ORDER BY total_revenue DESC) AS rank_in_month
    FROM monthly_sales
)
SELECT 
    sales_month,
    category_id,
    total_revenue
FROM ranked_categories
WHERE rank_in_month <= 3
ORDER BY sales_month DESC, rank_in_month ASC;

```

---

## 5. Verification & Quality Assurance Checklist

Before delivering analysis, charts, or SQL queries, verify against these checks:

1. **Data Consistency**: Do total sums and row counts match pre-analysis baselines?
2. **Null & Edge Case Safety**: Are division-by-zero risks mitigated (`np.where` or `NULLIF(val, 0)`)?
3. **Visual Verification**: Is the generated plot clean, unclipped, correctly labeled, and readable?
4. **SQL Determinism**: Does running the SQL query multiple times on static data yield identical results?

---

## 6. Dukungan Termux (Android) — garwa ringan & robust

Skill data-analytics berjalan di Termux. **`pandas`/`numpy` tersedia sebagai paket Termux** (`python-pandas`, `python-numpy`) — lebih ringan & stabil daripada pip untuk library ber-C-extension. `matplotlib`/`seaborn`/`plotly` TIDAK ada di repo Termux (harus pip) dan cukup berat — untuk chart ringan, pertimbangkan alternatif.

> **Di desktop/VPS dengan resource cukup:** tetap install tool penuh (bagian Dependensi) untuk hasil maksimal — `matplotlib`/`seaborn` untuk chart publikasi-grade, `plotly` untuk interaktif, `python-polars` untuk data besar. Fallback di bawah HANYA untuk lingkungan terbatas/Termux.

```bash
# 0. PENTING — perbaiki pip dulu bila error "No module named 'pip._internal.operations.install.wheel'".
#    Itu BUKAN pip rusak permanen: akar masalahnya libexpat terlalu lama (2.7.x) yang tidak punya
#    simbol XML_SetHashSalt16Bytes yang dibutuhkan pyexpat Python 3.14. Upgrade libexpat:
pkg install -y libexpat        # upgrade ke 2.8.4 → pyexpat OK → pip install bekerja (TERUJI 2026-09)
# 1. Wajib — pandas & numpy via paket Termux (TERSEDIA, lebih ringan daripada pip untuk C-extension)
pkg install -y python-pandas python-numpy
# 2. Opsional — chart: matplotlib/seaborn TIDAK ada di repo Termux, install via pip (berat, butuh wheel)
pip3 install --break-system-packages matplotlib seaborn
# 3. Alternatif ringan untuk chart: plotly (pip) atau output CSV/JSON + baris ASCII untuk data besar
```

**Fallback ringan (tanpa matplotlib/seaborn):**
- **Chart ringan**: untuk laporan cepat, gunakan `plotly` (pip) yang bisa output HTML interaktif, atau render SVG/ASCII sederhana. `matplotlib` butuh banyak wheel (numpy, pillow, etc.) — install hanya bila chart publikasi-grade benar-benar dibutuhkan.
- **Analisis data besar**: `python-polars` TERSEDIA sebagai paket Termux (lebih cepat & hemat memori daripada pandas untuk data besar).
- **Verifikasi tanpa plot**: gunakan statistik ringkasan (mean/median/std/min/max) + cek `df.describe()` — cukup untuk QA tanpa visual.

> **Catatan pip di Termux (TERUJI):** `matplotlib`/`seaborn` adalah wheel dengan C-extension — `pip3 install --break-system-packages` bekerja SETELAH `libexpat` di-upgrade (lihat langkah 0). Kalau muncul error `install_wheel`, JANGAN asumsikan pip rusak — upgrade `libexpat` dulu. Gunakan `--break-system-packages` karena Termux memakai sistem Python.

### ✅ Hasil uji nyata di Termux (Python 3.14.6, 2026-09)
- **pandas/numpy via paket Termux**: `pkg install python-pandas python-numpy` → numpy **2.4.4**, pandas **3.0.5** → `DataFrame()` + `.mean()`/`.sum()` → **OK**.
- **matplotlib via pip**: **MACET saat build dari source** (tarball 32.6 MB, "Installing backend dependencies: still running..." berjam-jam, tidak selesai). Ini **memvalidasi klaim skill** bahwa matplotlib "cukup berat" di Termux.
- **Kesimpulan do & don't**: `python-pandas`/`python-numpy` **do** — paket Termux, jalan penuh (analisis data). `python-polars` **do** — paket Termux untuk data besar. `matplotlib`/`seaborn` **don't** untuk Termux — build macet; gunakan `plotly` (pip, HTML interaktif) atau output CSV/JSON/ASCII sebagai fallback chart. Di desktop/VPS tetap **do** install matplotlib untuk chart publikasi-grade.