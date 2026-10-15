"""Unit tests for the clause-aware chunker — pure, no model or PDFs needed.

Feeds synthetic per-page text through chunk_pages/clean_pages/split_blocks
and checks clause structure, metadata integrity, and size/overlap bounds.
"""

from app.rag.chunker import (
    clean_pages,
    chunk_pages,
    detect_lang,
    estimate_tokens,
    extract_doc_id,
    extract_title,
    split_blocks,
)

ZH_COVER = [
    "第 1/3 頁",
    "香 港 特 別 行 政 區 政 府",
    "民航處",
    "小型無人機通告",
    "第 AC -014 號",
    "日期︰2026 年 7 月 31 日",
    "丙類小型無人機操作許可及預設情境 #1",
    "1. 背景",
    "1.1. 根據《小型無人機令》，小型無人機的操作是以風險為本的模式規管。",
]

EN_COVER = [
    "Page 1 of 2",
    "Civil Aviation Department",
    "Small Unmanned Aircraft Advisory Circular",
    "No. AC-010",
    "Date: 18 June 2026",
    "Guidelines and Permission for Drone Show Event",
    "1. Background",
    "1.1 The SUA Order came into operation on 1 June 2022.",
]


def test_doc_id_handles_spaced_zh_form():
    assert extract_doc_id("\n".join(ZH_COVER), "AC-014_C.pdf") == "AC-014"


def test_doc_id_handles_english_form():
    assert extract_doc_id("\n".join(EN_COVER), "AC-010.pdf") == "AC-010"


def test_doc_id_uca_variants():
    assert extract_doc_id("No. AC-UCA001", "UCA_AC-UCA001_insurance.pdf") == "AC-UCA001"
    assert (
        extract_doc_id("航行資料通報 AIC 20/25 的譯本", "UCA_AIC-20-25_x.pdf") == "AIC-20/25"
    )
    assert extract_doc_id("no id here", "UCA_ops_manual_template_ZH.pdf") == "UCA-OPS-MANUAL-TEMPLATE"


def test_title_between_date_and_first_section():
    assert extract_title("\n".join(ZH_COVER), None, "AC-014_C.pdf") == "丙類小型無人機操作許可及預設情境 #1"
    assert extract_title("\n".join(EN_COVER), None, "AC-010.pdf") == "Guidelines and Permission for Drone Show Event"


def test_title_falls_back_to_clean_metadata_then_filename():
    masthead_only = "香港特別行政區政府\n民航處\nCivil Aviation Department"
    assert extract_title(masthead_only, "AC-017 Permission for X", "f.pdf") == "AC-017 Permission for X"
    assert extract_title(masthead_only, "Microsoft Word - draft.docx", "f.pdf") == "f"


def test_title_without_date_line_takes_first_content_line():
    page = "非傳統航空器在港進行試飛活動的許可\n＜本中文譯本僅作參考之用＞\n1. 簡介\n1.1 低空經濟。"
    assert extract_title(page, "AIC 20-25 (Chi)", "x.pdf") == "非傳統航空器在港進行試飛活動的許可"


def test_clean_pages_drops_page_markers_and_repeated_headers():
    pages = [
        "Page 1 of 3\nHeader Line\nUnique one",
        "Page 2 of 3\nHeader Line\nUnique two",
        "Page 3 of 3\nHeader Line\nUnique three",
    ]
    cleaned = clean_pages(pages)
    flat = [ln for page in cleaned for ln in page]
    assert "Unique one" in flat and "Unique three" in flat
    assert all("Page " not in ln for ln in flat)
    # header repeats on 3 pages -> dropped from pages 2+ but kept on page 1
    assert flat.count("Header Line") == 1


def test_blocks_split_on_clause_headings_and_track_pages():
    pages = [
        ["1. 背景", "1.1 第一段。", "續行。"],
        ["1.2 第二段。", "2. 定義", "2.1 第三段。"],
    ]
    blocks = split_blocks(pages)
    clauses = [b.clause for b in blocks]
    assert clauses == ["1", "1.1", "1.2", "2", "2.1"]
    b11 = blocks[1]
    assert b11.text.startswith("1.1 第一段。") and "續行。" in b11.text
    assert (b11.page_start, b11.page_end) == (1, 1)
    assert (blocks[2].page_start, blocks[2].page_end) == (2, 2)


def test_cjk_spaces_collapsed_in_block_text():
    blocks = split_blocks([["1.1 香 港 特 別 行 政 區 政 府 民 航 處 。"]])
    assert "香港特別行政區政府民航處" in blocks[0].text


def test_ascii_hyphens_repaired():
    blocks = split_blocks([["1.1 Operations are risk -based and cross -boundary."]])
    assert "risk-based" in blocks[0].text and "cross-boundary" in blocks[0].text


def _sample_pages() -> list[str]:
    body = [
        "1. 背景",
        "1.1 " + "根據《小型無人機令》的規定，操作須以風險為本。" * 3,
        "1.2 " + "該類無人機的操作被歸類為進階操作。" * 3,
        "2. 操作要求",
        "2.1 " + "最高飛行高度為地面以上 300 呎。" * 3,
    ]
    return ["\n".join(ZH_COVER + body[:3]), "\n".join(["第 2/2 頁"] + body[3:])]


def test_chunk_pages_metadata_complete_and_cited():
    chunks = chunk_pages(_sample_pages(), doc_id="AC-014", doc_title="丙類", source_file="AC-014_C.pdf")
    assert chunks
    for c in chunks:
        cid, text, meta = c.record()
        assert cid == f"AC-014::{c.chunk_index:04d}"
        assert meta["doc_id"] == "AC-014" and meta["doc_title"] == "丙類"
        assert meta["source_file"] == "AC-014_C.pdf"
        assert meta["page_start"] >= 1 and meta["page_end"] >= meta["page_start"]
        assert meta["section"].startswith(("para.", "p."))
        assert text == c.text
    # the altitude clause must be retrievable with its clause number covered
    alt = [c for c in chunks if "300 呎" in c.text]
    assert alt and "2.1" in alt[0].extra["clauses"].split(",")
    assert alt[0].page_end >= 2  # clause sits on page 2 of the sample


def test_chunk_size_bounds_and_overlap():
    long_par = "1.1 " + "。".join(f"第{i}句操作要求說明" for i in range(120)) + "。"
    pages = ["\n".join(["1. 背景", long_par])]
    chunks = chunk_pages(
        pages, doc_id="AC-X", doc_title="t", source_file="x.pdf",
        max_tokens=120, overlap_tokens=30, token_counter=estimate_tokens,
    )
    assert len(chunks) > 1
    for c in chunks:
        assert estimate_tokens(c.text) <= 180  # bound: max + one sentence
    # consecutive chunks share trailing content (overlap)
    assert chunks[0].text[-30:] in chunks[1].text or any(
        s in chunks[1].text for s in chunks[0].text.split("。")[-4:]
    )


def test_detect_lang_and_estimate():
    assert detect_lang("香港特別行政區政府民航處小型無人機通告") == "zh"
    assert detect_lang("Small Unmanned Aircraft Advisory Circular") == "en"
    assert estimate_tokens("abcd" * 25) == 25
    assert estimate_tokens("香港" * 10) == 20
