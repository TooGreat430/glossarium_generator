"""Streamlit UI untuk Business Glossary Generator."""

import io
import re
# import os  # dipakai blok BigQuery di bagian bawah file

import pandas as pd
import streamlit as st

from generator import generate_glossary
from prompts import INPUT_COLS, OUTPUT_COLS

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


def _normalize(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _map_columns(df):
    """Return df dengan kolom kanonik + daftar kolom wajib yang hilang."""
    mapped = {}
    for col in df.columns:
        canonical = COLUMN_MAP.get(_normalize(col))
        if canonical and canonical not in mapped:
            mapped[canonical] = df[col]
    missing = [col for col in REQUIRED_COLS if col not in mapped]
    out = pd.DataFrame({col: mapped[col] for col in INPUT_COLS if col in mapped})
    if "Description" not in out.columns and not missing:
        out["Description"] = ""
    return out.fillna("").astype(str), missing


def _to_excel(df):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="glossary")
    return buffer.getvalue()


st.set_page_config(page_title="Business Glossary Generator", layout="wide")
st.title("Business Glossary Generator")
st.caption("Upload data dictionary (.xlsx), Gemini 2.5 Flash mengisi 8 kolom glossary.")

uploaded = st.file_uploader("File Excel data dictionary", type=["xlsx"])

if uploaded:
    raw = pd.read_excel(uploaded)
    df, missing = _map_columns(raw)

    if missing:
        st.error(f"Kolom input wajib tidak ditemukan: {', '.join(missing)}")
        st.stop()

    # --- Opsional: lewati baris yang kolom output-nya sudah terisi -----------
    # Aktifkan blok ini kalau file input SUDAH memuat kolom output yang sebagian
    # terisi (mis. domain Funding yang glossary-nya sudah dikerjakan), sehingga
    # hanya baris yang benar-benar kosong yang dikirim ke Gemini.
    # Tidak aktif karena file input saat ini tidak memuat kolom output sama sekali.
    #
    # raw_cols = {_normalize(c): c for c in raw.columns}
    # existing = [raw_cols[_normalize(c)] for c in OUTPUT_COLS if _normalize(c) in raw_cols]
    # if existing:
    #     filled = raw[existing].fillna("").astype(str).apply(
    #         lambda row: any(v.strip() for v in row), axis=1
    #     )
    #     st.info(f"{int(filled.sum())} baris sudah terisi, dilewati.")
    #     df = df.loc[~filled].reset_index(drop=True)

    st.success(f"{len(df)} baris terbaca.")
    st.dataframe(df.head(10), use_container_width=True)

    limit = st.number_input(
        "Batasi jumlah baris (untuk testing, 0 = semua baris)",
        min_value=0,
        max_value=len(df),
        value=0,
        step=100,
    )
    work_df = df.head(int(limit)) if limit else df

    if st.button("Generate", type="primary"):
        progress = st.progress(0.0)
        with st.status(f"Generate {len(work_df)} baris...", expanded=True) as status:
            def on_progress(done, total):
                progress.progress(done / total)
                rows_done = min(done * 5, len(work_df))
                status.update(label=f"Batch {done}/{total} selesai ({rows_done}/{len(work_df)} baris)")

            result, errors = generate_glossary(work_df, progress_cb=on_progress)
            status.update(label=f"Selesai: {len(result)} baris.", state="complete")

        st.session_state["result"] = result
        st.session_state["errors"] = errors

if "result" in st.session_state:
    result = st.session_state["result"]
    errors = st.session_state.get("errors", [])

    if errors:
        st.warning(
            f"{len(errors)} batch gagal setelah 3x retry, kolom output baris tersebut dikosongkan:\n\n"
            + "\n".join(f"- {e}" for e in errors[:20])
        )

    st.subheader("Hasil")
    st.dataframe(result[INPUT_COLS + OUTPUT_COLS].head(50), use_container_width=True)
    st.download_button(
        "Download hasil (.xlsx)",
        data=_to_excel(result),
        file_name="glossary_result.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # --- Opsional: simpan hasil ke BigQuery sebagai master data glossary -----
    # Belum diaktifkan. Untuk mengaktifkan:
    #   1. uncomment blok di bawah ini
    #   2. uncomment `google-cloud-bigquery[pandas]` di requirements.txt
    #   3. uncomment `import os` di bagian atas file ini
    #   4. deploy ulang (image harus di-build ulang untuk install dependency baru)
    #   5. beri service account Cloud Run role roles/bigquery.dataEditor
    #   6. buat dataset tujuannya lebih dulu (BigQuery tidak bikin otomatis)
    #
    # from google.cloud import bigquery
    #
    # BQ_TABLE = f"{os.environ['GCP_PROJECT']}.glossary.business_glossary"
    #
    # if st.button("Simpan ke BigQuery"):
    #     # Nama kolom seperti "Domain/Glossaries name" tidak valid di BigQuery,
    #     # jadi disanitasi jadi huruf kecil + underscore lebih dulu.
    #     bq_df = result.rename(
    #         columns=lambda c: re.sub(r"[^0-9a-zA-Z_]+", "_", c).strip("_").lower()
    #     )
    #     bq = bigquery.Client(project=os.environ["GCP_PROJECT"])
    #     job = bq.load_table_from_dataframe(
    #         bq_df,
    #         BQ_TABLE,
    #         job_config=bigquery.LoadJobConfig(
    #             autodetect=True,
    #             write_disposition="WRITE_APPEND",  # WRITE_TRUNCATE kalau mau timpa
    #         ),
    #     )
    #     job.result()
    #     st.success(f"{job.output_rows} baris tersimpan ke {BQ_TABLE}")
