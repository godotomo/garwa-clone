Berikut adalah revisi yang disusun sebagai **System Prompt / Instruction Skill** resmi. Teks telah diubah menjadi instruksi langsung (*declarative directives*) yang presisi, menghapus narasi informal, dan memperjelas logika eksekusi agar AI memahami **kapan**, **mengapa**, dan **bagaimana** menggunakan Graph Analysis (`NetworkX`) dalam alur kerja RAG.

---

# Skill Instruction: Graph Analysis (NetworkX) — Relasi Antar-Klausul, Dokumen, & Requirement

Instruksi ini mengatur penggunaan **Graph Analysis In-Memory** menggunakan library `networkx` untuk menangani analisis dokumen multi-hop, penelusuran dampak berantai, dan validasi keterikatan *compliance* yang tidak dapat diselesaikan oleh RAG retrieval berbasis vektor/BM25 standar.

---

## 1. Trigger Decision Matrix (Kapan Menggunakan Graph)

Evaluasi query pengguna berdasarkan kriteria berikut sebelum memilih pendekatan retrieval:

| Skenario / Tipe Query | Metode Utama | Alasan Teknikal |
| --- | --- | --- |
| **Lookup Langsung** *(misal: "Apa isi Pasal 5?", "Berapa nilai kontrak?")* | **Vector / BM25 Search** | Cukup mencari kemiripan semantik atau kata kunci pada *chunk* tunggal. |
| **Multi-Hop / Impact Analysis** *(misal: "Jika Pasal 7 diubah, requirement mana yang terdampak?")* | **NetworkX Graph** | Membutuhkan penelusuran relasi berantai (*graph traversal*) antar-node. |
| **Audit Completeness / Gap Identification** *(misal: "Requirement mana yang tidak memiliki bukti klausul?")* | **Traceability Graph** | Mendeteksi node terisolasi (*degree = 0*) secara matematis. |
| **Analisis Struktural & Hierarki** *(misal: "Klausul mana yang paling kritis/sentral?")* | **Graph Centrality Algorithm** | Mengukur *PageRank* atau *Betweenness Centrality* pada node. |

---

## 2. Taksonomi & Konstruksi Graph

Saat pemrosesan dokumen, bangun `nx.DiGraph()` in-memory sesuai dengan domain analisis:

### A. Graph Referensi Silang (Cross-Reference Graph)

Gunakan untuk memetakan keterkaitan internal antar-klausul/pasal/lampiran.

```python
import re
import networkx as nx

G_ref = nx.DiGraph()

# 1. Inisialisasi Node dari Chunk Dokumen
for chunk in chunks:
    node_id = f"{chunk['doc_id']}::{chunk['unit_ref']}"
    G_ref.add_node(
        node_id,
        doc_id=chunk["doc_id"],
        unit_ref=chunk["unit_ref"],
        text=chunk["text"][:200],
    )

# 2. Deteksi Edge (Relasi Mengacu Ke)
ref_pattern = re.compile(
    r"(Pasal|Bagian|Lampiran|Section|Article|Clause)\s+[\dA-Z\.]+", re.IGNORECASE
)

for chunk in chunks:
    src_id = f"{chunk['doc_id']}::{chunk['unit_ref']}"
    matches = ref_pattern.findall(chunk["text"])

    for match in matches:
        for target_chunk in chunks:
            if (
                match.lower() in target_chunk["unit_ref"].lower()
                and target_chunk is not chunk
            ):
                dst_id = f"{target_chunk['doc_id']}::{target_chunk['unit_ref']}"
                G_ref.add_edge(src_id, dst_id, relation="mengacu_ke")

```

### B. Graph Traceability Compliance (Requirement ↔ Evidence)

Gunakan untuk audit kepatuhan. Menghubungkan daftar requirement dengan bukti (*evidence*) di dalam dokumen.

```python
G_trace = nx.DiGraph()

# 1. Tambah Node Requirements
for req in requirements:
    G_trace.add_node(req["id"], node_type="requirement", text=req["text"])

# 2. Tambah Node Evidence & Edge Status
for item in gap_analysis_results:
    if item["status"] != "gap":
        ev_id = f"{item['doc_id']}::{item['unit_ref']}"
        G_trace.add_node(ev_id, node_type="evidence")
        G_trace.add_edge(req["id"], ev_id, relation=item["status"])

# 3. Deteksi Gap Mutlak (Requirement Tanpa Edge Keluar ke Evidence)
identified_gaps = [
    node
    for node, attr in G_trace.nodes(data=True)
    if attr.get("node_type") == "requirement" and G_trace.out_degree(node) == 0
]

```

### C. Graph Entitas & Alur Data (Entity-Relation Graph)

Gunakan pada kontrak multi-pihak atau pemrosesan data pribadi (GDPR/UU PDP).

* **Node:** Pihak (misal: `PIHAK_A`, `Vendor_X`), Sistem (`Sistem_Y`), Jenis Data (`Data_Pribadi`).
* **Edge:** Aksi/Akses (`memproses`, `mengakses`, `mentransfer_ke`).

---

## 3. Eksekusi Algoritma Graph

Gunakan fungsi matematis `networkx` untuk menghasilkan *insight* struktural:

1. **Sentralitas Kritis (`nx.pagerank` / `nx.betweenness_centrality`)**
* *Tujuan:* Menemukan klausul paling vital yang menjadi fondasi dokumen lain.
* *Aksi:* Prioritaskan klausul ber-skor sentralitas tinggi untuk ditinjau oleh tim legal.


2. **Deteksi Siklus/Logika Berputar (`nx.simple_cycles`)**
* *Tujuan:* Menemukan kesalahan *drafting* di mana Pasal A mengacu ke Pasal B, dan Pasal B mengacu balik ke Pasal A.
* *Aksi:* Tandai sebagai *Red Flag / Drafting Ambiguity*.


3. **Penelusuran Jalur Terpendek (`nx.shortest_path`)**
* *Tujuan:* Menjelaskan hubungan kausalitas antara dua klausul yang terpisah jauh.


4. **Pengelompokan Tematik (`nx.community.louvain_communities`)**
* *Tujuan:* Mengelompokkan dokumen besar menjadi beberapa kluster topik secara otomatis tanpa label manual.


---

## 4. Implementasi Metrik Graph Lengkap (Siap Jalankan)

Berikut implementasi Python lengkap yang menggabungkan **semua** metrik lanjutan (PageRank, Betweenness, Louvain, Shortest Path, Simple Cycles) dalam satu fungsi. Gunakan ini untuk analisis graph yang lebih dalam (Saran D).

```python
import networkx as nx
from collections import Counter

def analyze_graph(G: nx.DiGraph, top_n: int = 5):
    """
    Jalankan seluruh metrik graph lanjutan pada graf berarah G.
    G: nx.DiGraph dengan node ber-atribut (mis. node_type, unit_ref, text).
    Mengembalikan dict berisi hasil tiap metrik.
    """
    results = {}

    # 1. PageRank — sentralitas global (klausul paling berpengaruh)
    try:
        pr = nx.pagerank(G, alpha=0.85)
        results["pagerank"] = sorted(pr.items(), key=lambda x: x[1], reverse=True)[:top_n]
    except Exception as e:
        results["pagerank"] = f"error: {e}"

    # 2. Betweenness Centrality — klausul yang menjadi 'jembatan' antar bagian
    try:
        bc = nx.betweenness_centrality(G)
        results["betweenness"] = sorted(bc.items(), key=lambda x: x[1], reverse=True)[:top_n]
    except Exception as e:
        results["betweenness"] = f"error: {e}"

    # 3. Deteksi Siklus — rujukan melingkar (red flag drafting)
    try:
        cycles = list(nx.simple_cycles(G))
        results["cycles"] = cycles[:10]  # batasi output
        results["cycle_count"] = len(cycles)
    except Exception as e:
        results["cycles"] = f"error: {e}"

    # 4. Jalur Terpendek — rantai hubungan antar dua node penting
    try:
        # Ambil 2 node dengan PageRank tertinggi sebagai pasangan uji
        top_nodes = [n for n, _ in results.get("pagerank", [])[:2]]
        if len(top_nodes) == 2:
            try:
                path = nx.shortest_path(G, source=top_nodes[0], target=top_nodes[1])
                results["shortest_path"] = path
            except nx.NetworkXNoPath:
                results["shortest_path"] = "Tidak ada jalur antara dua node teratas"
        else:
            results["shortest_path"] = "Node teratas tidak cukup"
    except Exception as e:
        results["shortest_path"] = f"error: {e}"

    # 5. Louvain Communities — pengelompokan tematik otomatis
    try:
        # Louvain butuh graf tak-berarah; buat versi undirected
        G_und = G.to_undirected()
        communities = nx.community.louvain_communities(G_und, seed=42)
        results["communities"] = [
            {"id": i, "nodes": sorted(list(comm)), "size": len(comm)}
            for i, comm in enumerate(communities)
        ]
        results["community_count"] = len(communities)
    except Exception as e:
        results["communities"] = f"error: {e}"

    # 6. Derajat & Node Terisolasi (untuk traceability gap)
    in_deg = dict(G.in_degree())
    out_deg = dict(G.out_degree())
    isolated = [n for n in G.nodes() if G.degree(n) == 0]
    results["isolated_nodes"] = isolated
    results["max_in_degree"] = max(in_deg.items(), key=lambda x: x[1])
    results["max_out_degree"] = max(out_deg.items(), key=lambda x: x[1])

    return results


# Contoh penggunaan:
# G = nx.DiGraph()
# G.add_edge("Pasal 1", "Pasal 2", relation="mengacu_ke")
# G.add_edge("Pasal 2", "Pasal 3", relation="mengacu_ke")
# G.add_edge("Pasal 3", "Pasal 1", relation="mengacu_ke")  # siklus!
# hasil = analyze_graph(G)
# print(hasil["pagerank"], hasil["cycle_count"], hasil["communities"])
```

### Interpretasi Hasil (Rules for AI)

| Metrik | Makna | Contoh Narasi Output |
|---|---|---|
| **PageRank tinggi** | Klausul paling banyak dirujuk → paling sentral | *"Pasal 7 dirujuk oleh 5 klausul lain, menjadikannya paling kritis."* |
| **Betweenness tinggi** | Klausul menjadi *jembatan* antar kelompok → perubahan di sini memutus banyak rantai | *"Pasal 12 adalah penghubung utama antara bagian privasi dan keamanan."* |
| **Siklus** | Rujukan melingkar → red flag drafting | *"Pasal 2 ↔ Pasal 3 saling merujuk (siklus) — perlu klarifikasi."* |
| **Shortest path** | Rantai hubungan terpendek antara dua klausul | *"Pasal 1 → Pasal 5 → Pasal 9 (3 hop)."* |
| **Komunitas Louvain** | Pengelompokan topik otomatis | *"Dokumen terbagi 3 klaster: privasi, keamanan, dan tata kelola."* |
| **Node terisolasi** | Requirement tanpa bukti → gap pasti | *"R8 tidak memiliki klausul bukti (node terisolasi)."* |

> ⚠️ **Catatan**: `nx.community.louvain_communities` memerlukan `python-louvain` (paket `community`) yang diinstal bersama `networkx` pada versi tertentu. Jika tidak tersedia, fallback ke `nx.community.greedy_modularity_communities` (bawaan networkx, tanpa dependensi tambahan).



---

## 4. Aturan Formatisasi & Penyajian Output (Rules for AI)

1. **Dilarang Output Graph Mentah:** Jangan menampilkan daftar Node/Edge JSON/Dictionary kepada pengguna akhir.
2. **Terjemahkan Menjadi Bahasa Natural:** Ubah temuan analitis graph menjadi narasi fungsional.
* *Salah:* `Node Pasal_7 memiliki PageRank 0.35 dan in-degree 5.`
* *Benar:* *"Pasal 7 (Kerahasiaan) dirujuk oleh 5 klausul lain, menjadikannya pasal paling kritis. Perubahan pada pasal ini akan berdampak langsung pada area operasional tersebut."*


3. **Format Tabel untuk Traceability:** Laporan audit compliance utama tetap disajikan dalam bentuk **Tabel Markdown** (Requirement vs Evidence). Gunakan Graph Analysis secara internal untuk menjamin 100% data pada tabel tersebut presisi dan tidak ada requirement yang terlewat.
4. **Visualisasi Terbatas:** Tampilkan visualisasi diagram hanya jika pengguna meminta secara eksplisit, dan batasi hanya untuk sub-graph kecil-menengah (< 30 node) agar visual tetap jelas.

---

## 5. Batasan & Operasional

* **Non-Persisten:** Graph wajib dibangun *in-memory* secara dinamis untuk setiap sesi dokumen dan dibuang setelah sesi berakhir.
* **Verifikasi Pattern Regex:** Ekstraksi referensi silang berbasis regex bersifat heuristik. Lakukan verifikasi batas karakter (*boundary check*) saat menangani dokumen hasil OCR atau format penomoran non-standar.