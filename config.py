"""Konfigurasi terpusat: model, project, batching, dan setting output."""

# --- Vertex AI / GCP -------------------------------------------------------
# LOCATION adalah region Vertex AI (bukan region Cloud Run tempat app di-deploy).
PROJECT_ID = "bdi-onprem"
LOCATION = "asia-southeast1"

MODEL_NAME = "gemini-2.5-flash"
TEMPERATURE = 0.2
RESPONSE_MIME_TYPE = "application/json"

# --- Batching & concurrency ------------------------------------------------
BATCH_SIZE = 5      # jumlah baris per satu panggilan Gemini
MAX_WORKERS = 8     # jumlah batch yang diproses paralel
MAX_RETRIES = 3     # percobaan per batch sebelum kolom output dikosongkan

# --- BigQuery (opsional, lihat blok komentar di app.py) --------------------
BQ_DATASET = "glossary"
BQ_TABLE = "business_glossary"
BQ_WRITE_DISPOSITION = "WRITE_APPEND"  # WRITE_TRUNCATE kalau mau timpa

# --- UI & output -----------------------------------------------------------
PAGE_TITLE = "Business Glossary Generator"
PAGE_LAYOUT = "wide"
PAGE_CAPTION = "Upload data dictionary (.xlsx), Gemini 2.5 Flash mengisi 8 kolom glossary."
EXCEL_SHEET_NAME = "glossary"
DOWNLOAD_FILENAME = "glossary_result.xlsx"
PREVIEW_ROWS_INPUT = 10
PREVIEW_ROWS_RESULT = 50
MAX_ERRORS_SHOWN = 20
