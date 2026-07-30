"""Postprocessing: dari response Gemini jadi baris hasil dan file Excel.

Isi modul ini: normalisasi tiap kolom output (terms, labels, data_element),
perakitan baris hasil, penyusunan kolom untuk export, dan penulisan Excel.
"""

import io
import re

import pandas as pd

from config import EXCEL_SHEET_NAME
from preprocessing import clean_text
from prompts import OUTPUT_COLS

# Urutan dan header kolom di file Excel hasil akhir.
# Kunci = nama kolom internal, nilai = header yang ditulis ke Excel.
EXPORT_COLS = {
    "No.": "No.",
    "Domain/Glossaries name": "Domain/Glossaries name",
    "Logical Name": "Logical Name",
    "Table Name": "Table Name",
    "column_name": "column_name",
    "category_terminology": "category_terminology",
    "terminologi": "Terminologi",
    "Description": "Description",
    "related_terms": "related_terms",
    "synonym_terms": "synonym_terms",
    "labels": "labels",
    "contacts": "contacts",
    "overview": "overview",
    "data_element": "Data element",
}

# Gagal cepat kalau nanti ada kolom output baru yang lupa didaftarkan di atas,
# supaya kolomnya tidak diam-diam hilang dari Excel hasil.
assert set(OUTPUT_COLS) <= set(EXPORT_COLS), "ada kolom output yang belum masuk EXPORT_COLS"


def norm_terms(value):
    """related_terms / synonym_terms: dipisah koma, dedup case-insensitive."""
    out, seen = [], set()
    for term in clean_text(value).split(","):
        term = term.strip(" ,")
        if term and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return ", ".join(out)


def norm_labels(value, table_name):
    """labels: key:value dipisah " ; ", key di-snake_case, source_table dipaksa."""
    pairs = []
    seen = set()
    for part in clean_text(value).split(";"):
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


def norm_data_element(value):
    """data_element: snake_case dipisah ";", dedup."""
    out, seen = [], set()
    for elem in re.split(r"[;,]", clean_text(value)):
        elem = elem.strip().lower().replace(" ", "_")
        if elem and elem not in seen:
            seen.add(elem)
            out.append(elem)
    return ";".join(out)


def postprocess_item(item, row):
    """Satu objek hasil Gemini -> dict kolom output yang sudah dinormalisasi."""
    item = item if isinstance(item, dict) else {}
    result = {col: clean_text(item.get(col, "")) for col in OUTPUT_COLS}
    result["related_terms"] = norm_terms(result["related_terms"])
    result["synonym_terms"] = norm_terms(result["synonym_terms"])
    result["labels"] = norm_labels(result["labels"], clean_text(row.get("Table Name", "")))
    result["data_element"] = norm_data_element(result["data_element"])
    return result


def blank_item():
    """Kolom output kosong, dipakai kalau satu batch gagal setelah semua retry."""
    return {col: "" for col in OUTPUT_COLS}


def build_result_df(df, results):
    """Gabungkan df input dengan hasil per baris (dict index -> kolom output)."""
    out = df.copy().reset_index(drop=True)
    for col in OUTPUT_COLS:
        out[col] = [results.get(i, {}).get(col, "") for i in range(len(out))]
    return out


def reorder_for_export(df):
    """Susun kolom sesuai urutan template Excel hasil akhir, plus nomor urut."""
    out = df.copy()
    out.insert(0, "No.", list(range(1, len(out) + 1)))
    return out[list(EXPORT_COLS)].rename(columns=EXPORT_COLS)


def to_excel(df):
    """Return bytes file .xlsx untuk download_button Streamlit."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=EXCEL_SHEET_NAME)
    return buffer.getvalue()


def sanitize_bq_columns(df):
    """Nama kolom seperti "Domain/Glossaries name" tidak valid di BigQuery."""
    return df.rename(columns=lambda c: re.sub(r"[^0-9a-zA-Z_]+", "_", c).strip("_").lower())
