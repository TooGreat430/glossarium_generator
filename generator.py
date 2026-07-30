"""Generate business glossary columns with Gemini 2.5 Flash on Vertex AI."""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from google import genai
from google.genai import types

import config
from preprocessing import build_row_payload, make_batches
from postprocessing import blank_item, build_result_df, postprocess_item
from prompts import RESPONSE_SCHEMA, build_prompt


def _client():
    return genai.Client(
        vertexai=True,
        project=config.PROJECT_ID,
        location=config.LOCATION,
    )


def _call_batch(client, indices, rows):
    """Call Gemini once for a batch; return {row_id: item}. Raises on failure."""
    resp = client.models.generate_content(
        model=config.MODEL_NAME,
        contents=build_prompt([build_row_payload(i, row) for i, row in zip(indices, rows)]),
        config=types.GenerateContentConfig(
            temperature=config.TEMPERATURE,
            response_mime_type=config.RESPONSE_MIME_TYPE,
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
    for attempt in range(config.MAX_RETRIES):
        try:
            by_id = _call_batch(client, indices, rows)
            items = [postprocess_item(by_id[i], row) for i, row in zip(indices, rows)]
            return indices, items, None
        except Exception as exc:  # noqa: BLE001 - satu baris gagal tidak boleh mematikan job
            last_err = exc
            if attempt < config.MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
    blank = [blank_item() for _ in rows]
    return indices, blank, f"baris {indices[0] + 2}-{indices[-1] + 2}: {last_err}"


def generate_glossary(df: pd.DataFrame, progress_cb=None) -> tuple[pd.DataFrame, list[str]]:
    """Isi 8 kolom glossary untuk setiap baris df. Return (df hasil, daftar error)."""
    client = _client()
    batches = make_batches(df.to_dict("records"))

    results = {}
    errors = []
    done = 0
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
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

    return build_result_df(df, results), errors
