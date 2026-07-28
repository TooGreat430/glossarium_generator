"""Kontrak LLM: kolom, response schema, instruksi, few-shot, dan perakit prompt."""

import json

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

# row_id hanya dipakai untuk memetakan hasil kembali ke baris asal, tidak ikut
# ke output akhir. Kolom input tidak diminta balik ke Gemini.
RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "row_id": {"type": "INTEGER"},
            **{col: {"type": "STRING"} for col in OUTPUT_COLS},
        },
        "required": ["row_id"] + OUTPUT_COLS,
        "property_ordering": ["row_id"] + OUTPUT_COLS,
    },
}

INSTRUCTION = """Kamu adalah data steward perbankan Indonesia (financial banking, termasuk produk syariah).
Tugasmu melengkapi business glossary untuk kolom-kolom data dictionary.

Untuk SETIAP baris input, hasilkan row_id + 8 field berikut:
- row_id: SALIN PERSIS nilai row_id dari baris input yang bersangkutan. Jangan diubah, jangan dinomori ulang, jangan dikarang sendiri.
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
- Balikan HARUS berupa array JSON dengan panjang PERSIS sama dengan jumlah baris input.
- Setiap objek WAJIB memuat row_id milik baris input-nya. row_id dipakai untuk memetakan hasil kembali ke baris asal, jadi salah row_id berarti hasilnya masuk ke baris yang salah.
- Jangan mengembalikan kolom input (Logical Name, Table Name, column_name, Description) di output.
- Jangan mengosongkan field; kalau ragu, tetap isi dengan tebakan terbaik yang masuk akal."""

FEW_SHOT = [
    {
        "input": {
            "row_id": 7,
            "Domain/Glossaries name": "Funding",
            "Logical Name": "Percentage Zakat",
            "Table Name": "fact_fund_shr_addn_info",
            "column_name": "pct_zakat",
            "Description": "Percentage Zakat",
        },
        "output": {
            "row_id": 7,
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
            "row_id": 12,
            "Domain/Glossaries name": "Funding",
            "Logical Name": "Zakat Indonesian Rupiah Amount",
            "Table Name": "fact_fund_shr_addn_info",
            "column_name": "zakat_idr_amt",
            "Description": "Zakat Amount in IDR Currency",
        },
        "output": {
            "row_id": 12,
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
            "row_id": 33,
            "Domain/Glossaries name": "Funding",
            "Logical Name": "Zakat Original Amount",
            "Table Name": "fact_fund_shr_addn_info",
            "column_name": "zakat_orig_amt",
            "Description": "Zakat Amount in Original Currency",
        },
        "output": {
            "row_id": 33,
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


def build_prompt(rows):
    """Rakit prompt untuk satu batch baris input yang sudah dibersihkan."""
    return (
        f"{INSTRUCTION}\n\n"
        "CONTOH:\n"
        f"{json.dumps(FEW_SHOT, ensure_ascii=False, indent=2)}\n\n"
        f"Sekarang proses {len(rows)} baris berikut dan balikan array JSON berisi {len(rows)} objek:\n"
        f"{json.dumps(rows, ensure_ascii=False, indent=2)}"
    )
