# Chunking & Indexing (RAG Lokal — Hybrid: Keyword + Vector + Graph)

Skill ini menggunakan **retrieval lokal berbasis Python** tanpa ketergantungan pada API embedding eksternal/berbayar. Seluruh indeks dibangun secara dinamis per sesi dan disimpan di area penyimpanan sementara (`scratchpad` lokal / `/tmp`)[cite: 1]. 

> ⚠️ **Prinsip Operasional Indeks**: Indeks bersifat sementara (*session-bound*) dan **tidak persisten secara otomatis** antar-sesi[cite: 1]. Indeks diperlakukan sebagai komponen *once-off* yang dibangun ulang dari dokumen sumber setiap kali sesi analisis baru dimulai[cite: 1].

---

## Arsitektur Retrieval 3-Lapis (Hybrid Approach)

Pencarian dilakukan secara kombinatif (*hybrid retrieval*) dengan menggabungkan tiga lapisan berikut, bukan memilih salah satu[cite: 1]:

| Lapisan | Teknik / Pustaka | Peruntukan Utama | Akses Internet |
|---|---|---|---|
| **1. Keyword** | BM25 (`rank_bm25`) | *Baseline* utama untuk terminologi hukum/regulasi yang butuh *exact-match* presisi[cite: 1] | Tidak[cite: 1] |
| **2. Vector / Semantic** | FAISS + Embedding | Menangkap kesamaan makna, variasi frase, atau sinonim teknis[cite: 1] | Tergantung Tier[cite: 1] |
| **3. Graph** | NetworkX | Memetakan relasi multi-hop antar-klausul, dependensi, dan keterlacakan (*traceability*)[cite: 1] | Tidak[cite: 1] |

*Lihat rincian implementasi Graph pada file referensi `references/07-graph-analysis.md`[cite: 1].*

---

## Kriteria Bangun Indeks vs. Pembacaan Langsung

* **Pembacaan Langsung (Direct Context)**: Digunakan jika total ukuran dokumen muat secara nyaman dalam konteks aktif (dokumen tunggal pendek / beberapa dokumen ringkas)[cite: 1].
* **Konstruksi Indeks Wajib**: Berlaku untuk dokumen panjang (puluhan hingga ratusan halaman), agregasi banyak file, atau situasi di mana user akan melakukan serangkaian kueri berulang pada koleksi dokumen yang sama dalam satu sesi[cite: 1].

---

## Strategi Chunking Berbasis Struktur

1. **Pemotongan Struktural (Structural Chunking)**: Pemotongan wajib mengikuti konteks alami dokumen (per halaman untuk PDF, per pasal/klausul untuk kontrak, per *heading* untuk SOP/kebijakan, atau per kelompok baris untuk tabel)[cite: 1]. **Dilarang** memotong teks secara buta berdasarkan jumlah karakter (*fixed N-characters*) karena berisiko memutus klausul di tengah kalimat dan merusak makna yuridis[cite: 1].
2. **Sub-chunking**: Jika satu unit struktural terlalu panjang, bagi menjadi beberapa paragraf dengan *overlap* kecil (1–2 kalimat) guna menjaga kontinuitas konteks di batas pemotongan[cite: 1].
3. **Atribut Metadata Wajib**: Setiap *chunk* harus memiliki metadata: `doc_id`, `unit_ref` (untuk kepastian sitasi), `doc_type`, dan `text`[cite: 1].

---

## Lapisan 1: Indeks BM25 (Keyword Match)

Pustaka `rank_bm25` diprioritaskan karena performanya yang optimal dalam pencarian istilah spesifik, nomor pasal, dan terminologi ketat yang sering menjadi kunci utama pada pemeriksaan compliance[cite: 1].

```python
import json, re
from rank_bm25 import BM25Okapi

def tokenize(text):
    return re.findall(r"\w+", text.lower())

# Membaca data chunk yang tersimpan
with open("chunks.jsonl") as f:
    chunks = [json.loads(line) for line in f]

corpus_tokens = [tokenize(c["text"]) for c in chunks]
bm25 = BM25Okapi(corpus_tokens)

def search_bm25(query, top_k=8):
    scores = bm25.get_scores(tokenize(query))
    ranked = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [(chunks[i], scores[i]) for i in ranked if scores[i] > 0]

```

### Alternatif Lightweight: TF-IDF + Cosine Similarity

Jika lingkungan eksekusi tidak menyediakan `rank_bm25`, gunakan `TfidfVectorizer` dari `scikit-learn`:

```python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Catatan: Jangan aktifkan stop_words Inggris jika dokumen berbahasa Indonesia
vectorizer = TfidfVectorizer(stop_words=None)
X = vectorizer.fit_transform([c["text"] for c in chunks])
q = vectorizer.transform([query])
sims = cosine_similarity(q, X).flatten()

```

---

## Lapisan 2: Vector Search dengan FAISS

Gunakan pustaka `faiss-cpu` untuk pencarian vektor skala cepat. Penentuan metode *embedding* disesuaikan dengan ketersediaan jaringan:

### Tingkat A — Neural Embedding (Kualitas Semantik Maksimal)

Digunakan apabila lingkungan eksekusi memiliki akses keluar ke `huggingface.co` untuk mengunduh bobot model.

```python
from sentence_transformers import SentenceTransformer
import faiss, numpy as np, json

# Model ringan & multibahasa
model = SentenceTransformer('all-MiniLM-L6-v2')
# Untuk dokumen legal bahasa Indonesia/campuran:
# model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

with open("chunks.jsonl") as f:
    chunks = [json.loads(l) for l in f]

embeddings = model.encode([c["text"] for c in chunks], normalize_embeddings=True, show_progress_bar=False).astype("float32")

# FAISS Index Flat Inner Product (setara Cosine Similarity untuk vektor ter-normalisasi)
index = faiss.IndexFlatIP(embeddings.shape[1])
index.add(embeddings)

def search_vector(query, top_k=8):
    q = model.encode([query], normalize_embeddings=True).astype("float32")
    scores, idxs = index.search(q, top_k)
    return [(chunks[i], float(s)) for i, s in zip(idxs[0], scores[0]) if i != -1]

```

### Tingkat B — Fallback Offline Murni (TF-IDF + LSA)

Digunakan jika lingkungan eksekusi berada dalam jaringan tertutup/tanpa akses internet. Menggabungkan `TfidfVectorizer` dan `TruncatedSVD` (Latent Semantic Analysis) untuk mengekstrak vektor semantik tanpa mengunduh *neural model*.

```python
import faiss, numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD

texts = [c["text"] for c in chunks]
vec = TfidfVectorizer()
X = vec.fit_transform(texts)

# Batasi jumlah komponen agar tidak melebihi dimensi data
n_components = min(200, X.shape[1] - 1, X.shape[0] - 1)
svd = TruncatedSVD(n_components=n_components, random_state=42)
dense = svd.fit_transform(X).astype("float32")
faiss.normalize_L2(dense)

index = faiss.IndexFlatIP(dense.shape[1])
index.add(dense)

def search_vector_offline(query, top_k=8):
    q = svd.transform(vec.transform([query])).astype("float32")
    faiss.normalize_L2(q)
    scores, idxs = index.search(q, top_k)
    return [(chunks[i], float(s)) for i, s in zip(idxs[0], scores[0]) if i != -1]

```

> **Prosedur Pengujian**: Uji konektivitas Tingkat A terlebih dahulu dengan *timeout* singkat (~15 detik). Jika gagal karena isolasi jaringan, langsung beralih (*fallback*) ke Tingkat B secara otomatis.
> 
> 

---

## Penggabungan Hybrid: Reciprocal Rank Fusion (RRF)

Gabungkan peringkat dari BM25 dan FAISS secara sejajar untuk menghasilkan pembobotan yang seimbang antara kepastian kata kunci dan kemiripan konteks semantik.

```python
def hybrid_search(query, top_k=8):
    bm25_results = search_bm25(query, top_k=15)
    vector_results = search_vector(query, top_k=15)  # Gunakan Tingkat A atau B
    
    scores = {}
    # RRF Constant k = 60
    for rank, (chunk, _) in enumerate(bm25_results):
        key = (chunk["doc_id"], chunk["unit_ref"])
        scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        
    for rank, (chunk, _) in enumerate(vector_results):
        key = (chunk["doc_id"], chunk["unit_ref"])
        scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return ranked

```

---

## Implementasi Hybrid Retrieval Lengkap (Siap Jalankan)

Berikut implementasi end-to-end yang menggabungkan **BM25 + FAISS + RRF** dalam satu kelas siap-pakai, lengkap dengan **fallback otomatis** antara embedding neural (Tingkat A) dan offline LSA (Tingkat B) (Saran E).

```python
import json, re, os
import numpy as np
import faiss
from rank_bm25 import BM25Okapi

class HybridRetriever:
    """Retrieval hybrid 3-lapis: BM25 + FAISS (neural/offline) + RRF."""

    def __init__(self, chunks, model_name="all-MiniLM-L6-v2", timeout=15):
        self.chunks = chunks
        self._build_bm25()
        self._build_vector(model_name, timeout)

    def _tokenize(self, text):
        return re.findall(r"\w+", text.lower())

    def _build_bm25(self):
        corpus = [self._tokenize(c["text"]) for c in self.chunks]
        self.bm25 = BM25Okapi(corpus)

    def _build_vector(self, model_name, timeout):
        """Coba neural embedding (Tingkat A); fallback ke LSA offline (Tingkat B)."""
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(model_name)
            self.embeddings = self.model.encode(
                [c["text"] for c in self.chunks],
                normalize_embeddings=True, show_progress_bar=False,
            ).astype("float32")
            self.mode = "neural"
        except Exception:
            # Fallback Tingkat B: TF-IDF + LSA (offline murni)
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.decomposition import TruncatedSVD
            texts = [c["text"] for c in self.chunks]
            self.vec = TfidfVectorizer()
            X = self.vec.fit_transform(texts)
            n_comp = min(200, X.shape[1] - 1, X.shape[0] - 1)
            self.svd = TruncatedSVD(n_components=n_comp, random_state=42)
            self.embeddings = self.svd.fit_transform(X).astype("float32")
            faiss.normalize_L2(self.embeddings)
            self.mode = "lsa"
        self.index = faiss.IndexFlatIP(self.embeddings.shape[1])
        self.index.add(self.embeddings)

    def _search_bm25(self, query, top_k=15):
        scores = self.bm25.get_scores(self._tokenize(query))
        ranked = sorted(range(len(self.chunks)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [(self.chunks[i], float(scores[i])) for i in ranked if scores[i] > 0]

    def _search_vector(self, query, top_k=15):
        if self.mode == "neural":
            q = self.model.encode([query], normalize_embeddings=True).astype("float32")
        else:
            q = self.svd.transform(self.vec.transform([query])).astype("float32")
            faiss.normalize_L2(q)
        scores, idxs = self.index.search(q, top_k)
        return [(self.chunks[i], float(s)) for i, s in zip(idxs[0], scores[0]) if i != -1]

    def search(self, query, top_k=8, k=60):
        """Gabungkan BM25 + FAISS via Reciprocal Rank Fusion."""
        bm25_res = self._search_bm25(query, top_k=15)
        vec_res = self._search_vector(query, top_k=15)
        scores = {}
        for rank, (chunk, _) in enumerate(bm25_res):
            key = (chunk["doc_id"], chunk["unit_ref"])
            scores[key] = scores.get(key, 0) + 1 / (k + rank)
        for rank, (chunk, _) in enumerate(vec_res):
            key = (chunk["doc_id"], chunk["unit_ref"])
            scores[key] = scores.get(key, 0) + 1 / (k + rank)
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        # Kembalikan chunk lengkap (bukan hanya key)
        by_key = {(c["doc_id"], c["unit_ref"]): c for c in self.chunks}
        return [(by_key[key], score) for key, score in ranked]


# Contoh penggunaan:
# with open("chunks.jsonl") as f:
#     chunks = [json.loads(line) for line in f]
# retriever = HybridRetriever(chunks)   # otomatis pilih neural atau LSA
# hasil = retriever.search("pemberitahuan kebocoran data", top_k=8)
# for chunk, score in hasil:
#     print(chunk["doc_id"], chunk["unit_ref"], round(score, 3))
```

### Aturan Penggunaan HybridRetriever

1. **Fallback otomatis**: `HybridRetriever` mencoba neural embedding dulu; jika gagal (tidak ada internet / `sentence_transformers` tidak terpasang), otomatis beralih ke LSA offline. Tidak perlu kode fallback manual.
2. **Multi-query**: Untuk audit compliance, jalankan `search()` dengan beberapa variasi frasa sinonim (lihat "Aturan Khusus Audit Compliance" di bawah) dan gabungkan hasilnya.
3. **Top-K tinggi**: Gunakan `top_k=10–15` untuk audit compliance guna menekan false negative.
4. **Verifikasi kontekstual**: Selalu baca ulang chunk hasil retrieval secara utuh sebelum dijadikan dasar klaim/sitasi.

---

## Aturan Khusus Audit Compliance & Analisis Legal

1. **Penerapan Multi-Query**: Jalankan kueri dengan variasi frasa sinonim (misal: `"pemberitahuan kebocoran data"`, `"data breach notification"`, `"insiden keamanan"`, `"72 jam"`) untuk mengantisipasi perbedaan terminologi antara standar eksternal dan dokumen internal.

2. **Parameter Top-K Tinggi**: Atur nilai $k$ lebih besar ($k=10\text{--}15$) dibandingkan kueri umum ($k=5\text{--}8$) untuk menekan risiko *false negative* (klausul relevan yang terlewat).

3. **Verifikasi Kontekstual**: Potongan *chunk* hasil retrieval wajib dibaca dan diverifikasi ulang secara utuh sebelum digunakan sebagai basis klaim atau penyusunan sitasi laporan.
