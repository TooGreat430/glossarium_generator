"""Streamlit UI untuk Business Glossary Generator."""

import pandas as pd
import streamlit as st

import config
from generator import generate_glossary
from preprocessing import map_columns
from postprocessing import reorder_for_export, to_excel

st.set_page_config(page_title=config.PAGE_TITLE, layout=config.PAGE_LAYOUT)
st.title(config.PAGE_TITLE)
st.caption(config.PAGE_CAPTION)

uploaded = st.file_uploader("File Excel data dictionary", type=["xlsx"])

if uploaded:
    raw = pd.read_excel(uploaded)
    df, missing = map_columns(raw)

    if missing:
        st.error(f"Kolom input wajib tidak ditemukan: {', '.join(missing)}")
        st.stop()

    # --- Opsional: lewati baris yang kolom output-nya sudah terisi -----------
    # Aktifkan blok ini kalau file input SUDAH memuat kolom output yang sebagian
    # terisi, sehingga hanya baris yang benar-benar kosong yang dikirim ke Gemini.
    # Tidak aktif karena file input saat ini tidak memuat kolom output sama sekali.
    # Logikanya ada di preprocessing.filled_row_mask().
    #
    # from preprocessing import filled_row_mask
    #
    # filled = filled_row_mask(raw)
    # if filled.any():
    #     st.info(f"{int(filled.sum())} baris sudah terisi, dilewati.")
    #     df = df.loc[~filled].reset_index(drop=True)

    st.success(f"{len(df)} baris terbaca.")
    st.dataframe(df.head(config.PREVIEW_ROWS_INPUT), use_container_width=True)

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
                rows_done = min(done * config.BATCH_SIZE, len(work_df))
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
            f"{len(errors)} batch gagal setelah {config.MAX_RETRIES}x retry, "
            "kolom output baris tersebut dikosongkan:\n\n"
            + "\n".join(f"- {e}" for e in errors[:config.MAX_ERRORS_SHOWN])
        )

    final = reorder_for_export(result)

    st.subheader("Hasil")
    st.dataframe(final.head(config.PREVIEW_ROWS_RESULT), use_container_width=True)
    st.download_button(
        "Download hasil (.xlsx)",
        data=to_excel(final),
        file_name=config.DOWNLOAD_FILENAME,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # --- Opsional: simpan hasil ke BigQuery sebagai master data glossary -----
    # Belum diaktifkan. Untuk mengaktifkan:
    #   1. uncomment blok di bawah ini
    #   2. uncomment `google-cloud-bigquery[pandas]` di requirements.txt
    #   3. deploy ulang (image harus di-build ulang untuk install dependency baru)
    #   4. beri service account Cloud Run role roles/bigquery.dataEditor
    #   5. buat dataset tujuannya lebih dulu (BigQuery tidak bikin otomatis)
    #
    # from google.cloud import bigquery
    #
    # from postprocessing import sanitize_bq_columns
    #
    # BQ_TABLE_ID = f"{config.PROJECT_ID}.{config.BQ_DATASET}.{config.BQ_TABLE}"
    #
    # if st.button("Simpan ke BigQuery"):
    #     bq = bigquery.Client(project=config.PROJECT_ID)
    #     job = bq.load_table_from_dataframe(
    #         sanitize_bq_columns(result),
    #         BQ_TABLE_ID,
    #         job_config=bigquery.LoadJobConfig(
    #             autodetect=True,
    #             write_disposition=config.BQ_WRITE_DISPOSITION,
    #         ),
    #     )
    #     job.result()
    #     st.success(f"{job.output_rows} baris tersimpan ke {BQ_TABLE_ID}")
