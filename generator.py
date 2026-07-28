"""Generate business glossary columns with Gemini 2.5 Flash on Vertex AI."""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash"
BATCH_SIZE = 5
MAX_WORKERS = 8
MAX_RETRIES = 3

INPUT_COLS = [
    "Domain/Glossaries name",
    "Logical Name",
    "Table Name",
    "column_name",
    "Description",
]

OUTPUT_COLS = [
    "category_terminology",
    "terminologi",
    "related_terms",
    "synonym_terms",
    "labels",
    "contacts",
    "overview",
    "data_element",
]

RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {col: {"type": "STRING"} for col in OUTPUT_COLS},
        "required": OUTPUT_COLS,
        "property_ordering": OUTPUT_COLS,
    },
}

FEW_SHOT = [
    {
        "input": {
            "Domain/Glossaries name": "Funding",
            "Logical Name": "Percentage Zakat",
            "Table Name": "fact_fund_shr_addn_info",
            "column_name": "pct_zakat",
            "Description": "Percentage Zakat",
        },
        "output": {
            "category_terminology": "Funding Syariah",
            "terminologi": "Zakat Percentage",
            "related_terms": "Jumlah Zakat (Zakat Amount), Dana Syariah (Sharia Fund), Bagi Hasil (Profit Sharing)",
            "synonym_terms": "Tarif Zakat (Zakat Rate), Rasio Zakat (Zakat Allocation Percentage), Pct Zakat",
            "labels": "domain:funding ; subdomain:sharia_funding ; data_type:metric ; owner:funding_team ; business_process:zakat ; source_table:fact_fund_shr_addn_info",
            "contacts": "Tim Funding Syariah",
            "overview": "Persentase dana yang dialokasikan sebagai zakat sesuai ketentuan syariah (the percentage of funds allocated as zakat in accordance with sharia principles)",
            "data_element": "balance",
        },
    },
    {
        "input": {
            "Domain/Glossaries name": "Funding",
            "Logical Name": "Zakat Indonesian Rupiah Amount",
            "Table Name": "fact_fund_shr_addn_info",
            "column_name": "zakat_idr_amt",
            "Description": "Zakat Amount in IDR Currency",
        },
        "output": {
            "category_terminology": "Funding Syariah",
            "terminologi": "Jumlah Zakat dalam Rupiah",
            "related_terms": "Persentase Zakat (Zakat Percentage), Jumlah Zakat dalam Mata Uang Asli (Zakat Amount in Original Currency), Dana Syariah (Sharia Fund), Saldo Dana (Fund Balance), Bagi Hasil (Profit Sharing), Nilai Tukar Mata Uang (Exchange Rate)",
            "synonym_terms": "Jumlah Zakat dalam Rupiah (Zakat Indonesian Rupiah Amount)",
            "labels": "domain:funding ; subdomain:sharia_funding ; data_type:financial_amount ; owner:funding_team ; business_process:zakat ; source_table:fact_fund_shr_addn_info",
            "contacts": "Tim Funding Syariah",
            "overview": "Nominal zakat yang telah dikonversi dan dicatat dalam mata uang Rupiah Indonesia (IDR) (the zakat amount that has been converted and recorded in Indonesian Rupiah)",
            "data_element": "balance;currency",
        },
    },
    {
        "input": {
            "Domain/Glossaries name": "Funding",
            "Logical Name": "Zakat Original Amount",
            "Table Name": "fact_fund_shr_addn_info",
            "column_name": "zakat_orig_amt",
            "Description": "Zakat Amount in Original Currency",
        },
        "output": {
            "category_terminology": "Funding Syariah",
            "terminologi": "Jumlah Zakat dalam Mata Uang Asli (Zakat Amount in Original Currency)",
            "related_terms": "Persentase Zakat (Zakat Percentage), Jumlah Zakat dalam Mata Uang Lokal (Zakat Amount in Local Currency), Dana Syariah (Sharia Fund), Saldo Dana (Fund Balance)",
            "synonym_terms": "Zakat Original Amount, Original Currency Zakat Amount, Zakat Orig Amt, Amount Zakat, Nilai Zakat",
            "labels": "domain:funding ; subdomain:sharia_funding ; data_type:financial_amount ; owner:funding_team ; business_process:zakat ; source_table:fact_fund_shr_addn_info",
            "contacts": "Tim Funding Syariah",
            "overview": "Nominal zakat yang tercatat dalam mata uang asli transaksi atau rekening (the zakat amount recorded in the original transaction or account currency)",
            "data_element": "balance;currency",
        },
    },
]

INSTRUCTION = """Kamu adalah data steward perbankan Indonesia (financial banking, termasuk produk syariah).
Tugasmu melengkapi business glossary untuk kolom-kolom data dictionary.

Untuk SETIAP baris input, hasilkan 8 field berikut:
- category_terminology: sub-folder / business process tempat term dikelompokkan, contoh "Funding Syariah".
- terminologi: nama baku/standar dari business term, metric, atau KPI. Gaya bilingual "Nama Indonesia (English Name)" bila relevan.
- related_terms: istilah lain yang berhubungan secara konseptual tapi BUKAN hal yang sama. Dipisah koma, gaya bilingual "Nama Indonesia (English Name)".
- synonym_terms: sinonim / singkatan / akronim yang artinya PERSIS SAMA. Dipisah koma.
- labels: key-value dipisah " ; " dengan format key:value, wajib memuat domain, subdomain, data_type, owner, business_process, source_table.
- contacts: tim / data steward pemilik term, contoh "Tim Funding Syariah".
- overview: penjelasan 2-4 kalimat dalam Bahasa Indonesia lalu terjemahan English di dalam kurung.
- data_element: data yang dibutuhkan untuk membentuk kolom tersebut, satu kata atau beberapa dipisah ";", contoh "balance", "balance;currency", "date", "identifier".

Aturan:
- Bahasa campuran Indonesia + English mengikuti gaya contoh.
- Field "Description" pada input adalah INPUT, jangan digenerate ulang.
- source_table pada labels harus sama persis dengan "Table Name" baris tersebut.
- Balikan HARUS berupa array JSON dengan panjang PERSIS sama dengan jumlah baris input, urutannya sama.
- Jangan mengosongkan field; kalau ragu, tetap isi dengan tebakan terbaik yang masuk akal."""


def _client():
    return genai.Client(
        vertexai=True,
        project=os.environ["GCP_PROJECT"],
        location=os.environ.get("GCP_LOCATION", "us-central1"),
    )


def _row_payload(row):
    return {col: _clean(row.get(col, "")) for col in INPUT_COLS}


def _build_prompt(rows):
    examples = [{"input": ex["input"], "output": ex["output"]} for ex in FEW_SHOT]
    return (
        f"{INSTRUCTION}\n\n"
        "CONTOH:\n"
        f"{json.dumps(examples, ensure_ascii=False, indent=2)}\n\n"
        f"Sekarang proses {len(rows)} baris berikut dan balikan array JSON berisi {len(rows)} objek:\n"
        f"{json.dumps(rows, ensure_ascii=False, indent=2)}"
    )


def _call_batch(client, rows):
    """Call Gemini once for a batch of rows; raises on definitive failure."""
    resp = client.models.generate_content(
        model=MODEL,
        contents=_build_prompt(rows),
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )
    data = json.loads(resp.text)
    if not isinstance(data, list) or len(data) != len(rows):
        raise ValueError(f"expected {len(rows)} objects, got {len(data) if isinstance(data, list) else type(data)}")
    return data


def _process_batch(client, indices, rows):
    """Return (indices, results, error_message_or_None) with retry + backoff."""
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            data = _call_batch(client, rows)
            return indices, [_postprocess(item, row) for item, row in zip(data, rows)], None
        except Exception as exc:  # noqa: BLE001 - satu baris gagal tidak boleh mematikan job
            last_err = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
    blank = [{col: "" for col in OUTPUT_COLS} for _ in rows]
    return indices, blank, f"baris {indices[0] + 2}-{indices[-1] + 2}: {last_err}"


# --- postprocessing ---------------------------------------------------------

def _clean(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _norm_labels(value, table_name):
    pairs = []
    seen = set()
    for part in _clean(value).split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        key, val = part.split(":", 1)
        key, val = key.strip().lower().replace(" ", "_"), val.strip()
        if not key or not val or key in seen:
            continue
        seen.add(key)
        pairs.append((key, val))
    pairs = [(k, v) for k, v in pairs if k != "source_table"]
    if table_name:
        pairs.append(("source_table", table_name))
    return " ; ".join(f"{k}:{v}" for k, v in pairs)


def _norm_terms(value):
    out, seen = [], set()
    for term in _clean(value).split(","):
        term = term.strip(" ,")
        if term and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return ", ".join(out)


def _norm_data_element(value):
    out, seen = [], set()
    for elem in re.split(r"[;,]", _clean(value)):
        elem = elem.strip().lower().replace(" ", "_")
        if elem and elem not in seen:
            seen.add(elem)
            out.append(elem)
    return ";".join(out)


def _postprocess(item, row):
    item = item if isinstance(item, dict) else {}
    result = {col: _clean(item.get(col, "")) for col in OUTPUT_COLS}
    result["related_terms"] = _norm_terms(result["related_terms"])
    result["synonym_terms"] = _norm_terms(result["synonym_terms"])
    result["labels"] = _norm_labels(result["labels"], _clean(row.get("Table Name", "")))
    result["data_element"] = _norm_data_element(result["data_element"])
    return result


# --- public API -------------------------------------------------------------

def generate_glossary(df: pd.DataFrame, progress_cb=None) -> tuple[pd.DataFrame, list[str]]:
    """Isi 8 kolom glossary untuk setiap baris df. Return (df hasil, daftar error)."""
    client = _client()
    records = df.to_dict("records")
    batches = [
        (list(range(i, min(i + BATCH_SIZE, len(records)))), records[i:i + BATCH_SIZE])
        for i in range(0, len(records), BATCH_SIZE)
    ]

    results = {}
    errors = []
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(_process_batch, client, idx, rows) for idx, rows in batches]
        for future in as_completed(futures):
            indices, items, error = future.result()
            for i, item in zip(indices, items):
                results[i] = item
            if error:
                errors.append(error)
            done += 1
            if progress_cb:
                progress_cb(done, len(batches))

    out = df.copy().reset_index(drop=True)
    for col in OUTPUT_COLS:
        out[col] = [results.get(i, {}).get(col, "") for i in range(len(out))]
    return out, errors
