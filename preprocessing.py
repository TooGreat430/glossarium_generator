"""Preprocessing: dari file Excel mentah jadi input yang siap dikirim ke Gemini.

Isi modul ini: normalisasi nama kolom, pemetaan ke kolom kanonik, pembersihan
teks, perakitan payload per baris, dan pembagian baris jadi batch.
"""

import re

import pandas as pd

from config import BATCH_SIZE
from prompts import INPUT_COLS, OUTPUT_COLS

# Kolom input yang wajib ada di file Excel yang diupload.
REQUIRED_COLS = ["Domain/Glossaries name", "Logical Name", "Table Name", "column_name"]

# key = nama kolom Excel yang sudah dinormalisasi (huruf kecil, tanpa non-alfanumerik)
COLUMN_MAP = {
    "domainglossariesname": "Domain/Glossaries name",
    "domainglossaryname": "Domain/Glossaries name",
    "glossariesname": "Domain/Glossaries name",
    "domain": "Domain/Glossaries name",
    "logicalname": "Logical Name",
    "logical": "Logical Name",
    "tablename": "Table Name",
    "table": "Table Name",
    "columnname": "column_name",
    "column": "column_name",
    "physicalname": "column_name",
    "description": "Description",
    "deskripsi": "Description",
}


def normalize_name(name):
    """Nama kolom -> huruf kecil tanpa karakter non-alfanumerik, untuk matching."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def clean_text(value):
    """Rapikan nilai sel: NaN/None jadi "", whitespace berlebih jadi satu spasi."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def map_columns(df):
    """Return (df dengan kolom kanonik, daftar kolom wajib yang hilang)."""
    mapped = {}
    for col in df.columns:
        canonical = COLUMN_MAP.get(normalize_name(col))
        if canonical and canonical not in mapped:
            mapped[canonical] = df[col]
    missing = [col for col in REQUIRED_COLS if col not in mapped]
    out = pd.DataFrame({col: mapped[col] for col in INPUT_COLS if col in mapped})
    if "Description" not in out.columns and not missing:
        out["Description"] = ""
    return out.fillna("").astype(str), missing


def filled_row_mask(raw):
    """Mask baris yang kolom output-nya sudah terisi di file input.

    Dipakai kalau file input SUDAH memuat kolom output yang sebagian terisi
    (mis. domain Funding yang glossary-nya sudah dikerjakan), sehingga hanya
    baris yang benar-benar kosong yang perlu dikirim ke Gemini. Kalau file
    input tidak memuat kolom output sama sekali, mask-nya semua False.
    """
    raw_cols = {normalize_name(c): c for c in raw.columns}
    existing = [
        raw_cols[normalize_name(c)] for c in OUTPUT_COLS if normalize_name(c) in raw_cols
    ]
    if not existing:
        return pd.Series(False, index=raw.index)
    return raw[existing].fillna("").astype(str).apply(
        lambda row: any(v.strip() for v in row), axis=1
    )


def build_row_payload(row_id, row):
    """Kolom input + row_id sebagai kunci pemetaan hasil ke baris asal."""
    payload = {"row_id": row_id}
    payload.update({col: clean_text(row.get(col, "")) for col in INPUT_COLS})
    return payload


def make_batches(records, batch_size=BATCH_SIZE):
    """Bagi records jadi [(indices, rows), ...] sesuai batch_size."""
    return [
        (list(range(i, min(i + batch_size, len(records)))), records[i:i + batch_size])
        for i in range(0, len(records), batch_size)
    ]
