"""Generate business glossary columns with Gemini 2.5 Flash on Vertex AI."""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from google import genai
from google.genai import types

from prompts import INPUT_COLS, OUTPUT_COLS, RESPONSE_SCHEMA, build_prompt

MODEL = "gemini-2.5-flash"
BATCH_SIZE = 5
MAX_WORKERS = 8
MAX_RETRIES = 3


def _client():
    return genai.Client(
        vertexai=True,
        project=os.environ["GCP_PROJECT"],
        location=os.environ.get("GCP_LOCATION", "us-central1"),
    )


def _row_payload(row_id, row):
    """Kolom input + row_id sebagai kunci pemetaan hasil ke baris asal."""
    payload = {"row_id": row_id}
    payload.update({col: _clean(row.get(col, "")) for col in INPUT_COLS})
    return payload


def _call_batch(client, indices, rows):
    """Call Gemini once for a batch; return {row_id: item}. Raises on failure."""
    resp = client.models.generate_content(
        model=MODEL,
        contents=build_prompt([_row_payload(i, row) for i, row in zip(indices, rows)]),
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )
    data = json.loads(resp.text)
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON array, got {type(data).__name__}")

    # Petakan berdasarkan row_id, bukan urutan array, supaya hasil tidak bisa
    # nyangkut ke baris lain kalau Gemini mengubah urutan atau melewatkan baris.
    by_id = {}
    for item in data:
        if isinstance(item, dict) and item.get("row_id") is not None:
            by_id[int(item["row_id"])] = item
    missing = [i for i in indices if i not in by_id]
    if missing:
        raise ValueError(f"row_id tidak lengkap di response, hilang: {missing}")
    return by_id


def _process_batch(client, indices, rows):
    """Return (indices, results, error_message_or_None) with retry + backoff."""
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            by_id = _call_batch(client, indices, rows)
            return indices, [_postprocess(by_id[i], row) for i, row in zip(indices, rows)], None
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
