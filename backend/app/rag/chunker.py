"""Clause-aware chunking of CAD advisory circulars (project-plan §7 step 2.1).

Pipeline per PDF:
  1. extract per-page text with pypdf;
  2. drop boilerplate — page markers ("Page 1 of 16" / "第 1/17 頁") and
     header/footer lines that repeat across pages;
  3. merge wrapped lines into clause blocks — a new block starts at a
     numbered-paragraph heading ("1.1", "1.1.", "2.1 (a) …") or an appendix
     heading, so every chunk can cite its clause number (anti-hallucination
     rule: citations must carry clause numbers);
  4. pack blocks into ~500-token chunks with ~80-token overlap, splitting
     oversized blocks at sentence boundaries.

The module is pure: token counting is injected (`token_counter`), so unit
tests run without the embedding model/tokenizer. PDF extraction needs pypdf.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# --- tunables ---------------------------------------------------------------

DEFAULT_MAX_TOKENS = 500
DEFAULT_OVERLAP_TOKENS = 80
# Blocks shorter than this are glued to the previous block — headings like
# "1. 背景" alone or stray list markers carry no retrieval value.
MIN_BLOCK_TOKENS = 25

CJK_RE = re.compile(r"[一-鿿]")
PAGE_MARKER_RE = re.compile(
    r"^(?:第\s*\d+\s*/\s*\d+\s*頁|Page\s+\d+\s+of\s+\d+|第\s*\[\s*x\s*]\s*版.*)$"
)
# "1." / "1.1" / "1.1." / "12.3.4" at line start, followed by text or EOL.
CLAUSE_HEADING_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})[.、]?(?:\s+|$)")
APPENDIX_HEADING_RE = re.compile(
    r"^(附錄|附件|附表|APPENDIX|Appendix|ANNEX|Annex)(?:\s+[A-ZＡ-Ｚ\d])?"
)
# Date line separating the cover header from the document title.
DATE_LINE_RE = re.compile(r"(日期|Date)\s*[:︰]")

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?;；])\s*|(?<=[.])\s+(?=[A-Z(\"“])")


@dataclass
class Block:
    """One clause (numbered paragraph) of a circular, or front matter."""

    clause: str | None  # e.g. "3.2", None for cover/front matter
    text: str
    page_start: int
    page_end: int


@dataclass
class Chunk:
    """A retrievable unit with full citation metadata."""

    doc_id: str
    doc_title: str
    chunk_index: int
    text: str
    clause: str | None
    page_start: int
    page_end: int
    lang: str
    source_file: str
    extra: dict = field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        return f"{self.doc_id}::{self.chunk_index:04d}"

    @property
    def section_label(self) -> str:
        """Human citation label, e.g. 'para. 3.2' or 'p. 7' for unnumbered text."""
        return f"para. {self.clause}" if self.clause else f"p. {self.page_start}"

    def record(self) -> tuple[str, str, dict]:
        """(id, document, metadata) triple for the vector store."""
        metadata = {
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "section": self.section_label,
            "clause": self.clause or "",
            "page_start": self.page_start,
            "page_end": self.page_end,
            "lang": self.lang,
            "source_file": self.source_file,
            "chunk_index": self.chunk_index,
            **self.extra,
        }
        return self.chunk_id, self.text, metadata


# --- text normalisation -----------------------------------------------------


def normalize_text(text: str) -> str:
    """Repair pypdf extraction artefacts without touching semantics."""
    # pypdf emits \x01-style control chars for unmapped glyphs in some ACs
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    # pypdf breaks CJK words with spaces: "香 港 特 別 行 政 區" -> "香港特別行政區"
    text = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", text)
    # "乙類及 / 或" -> "乙類及/或"
    text = re.sub(r"(?<=[一-鿿])\s*/\s*(?=[一-鿿])", "/", text)
    # and splits ASCII hyphens: "risk -based" -> "risk-based"
    text = re.sub(r"(?<=[A-Za-z])\s+-(?=[A-Za-z])", "-", text)
    return text.strip()


def detect_lang(text: str) -> str:
    cjk = len(CJK_RE.findall(text))
    return "zh" if cjk > max(4, 0.15 * len(text)) else "en"


def estimate_tokens(text: str) -> int:
    """Cheap bge-m3 approximation: CJK ~1 token/char, ASCII ~1 token/4 chars.

    Used when no real tokenizer is injected (unit tests); the ingest script
    passes the model's own tokenizer for faithful counts.
    """
    cjk = len(CJK_RE.findall(text))
    return cjk + (len(text) - cjk) // 4


# --- PDF extraction ---------------------------------------------------------


def extract_pages(pdf_path: str | Path) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return [page.extract_text() or "" for page in reader.pages]


def _boilerplate_lines(pages: list[str]) -> set[str]:
    """Lines on most pages are running headers/footers, not content.

    CAD circulars repeat the department masthead on every page. A short line
    appearing on >=60% of pages (min 2) is boilerplate; the page-1 occurrence
    is kept by clean_pages so the cover header survives.
    """
    seen_on: dict[str, int] = {}
    for page in pages:
        for line in {normalize_text(ln) for ln in page.splitlines()}:
            if line and len(line) < 80:
                seen_on[line] = seen_on.get(line, 0) + 1
    threshold = max(2, -(-len(pages) * 3 // 5))  # ceil(0.6 * n_pages)
    return {ln for ln, n in seen_on.items() if n >= threshold}


def clean_pages(pages: list[str]) -> list[list[str]]:
    """Per page: normalised content lines with boilerplate removed.

    Page 1 keeps everything — the cover header carries the doc number/title.
    """
    boilerplate = _boilerplate_lines(pages)
    cleaned: list[list[str]] = []
    for i, page in enumerate(pages):
        lines = []
        for raw in page.splitlines():
            line = normalize_text(raw)
            if not line or PAGE_MARKER_RE.match(line):
                continue
            if i > 0 and line in boilerplate:
                continue
            lines.append(line)
        cleaned.append(lines)
    return cleaned


# --- document identity ------------------------------------------------------


def extract_doc_id(first_page: str, filename: str) -> str:
    """'第 AC -014 號' / 'No. AC-010' -> 'AC-014'; UCA docs keep their own ids."""
    stem = Path(filename).stem
    if stem.startswith("UCA"):
        if m := re.search(r"AC\s*-\s*UCA\s*0*(\d+)", first_page, re.I):
            return f"AC-UCA{m.group(1).zfill(3)}"
        if m := re.search(r"AIC\s*(\d+)\s*[/\-]\s*(\d+)", first_page, re.I):
            return f"AIC-{m.group(1)}/{m.group(2)}"
        slug = re.sub(r"[_ ](zh|en|c)$", "", stem[4:], flags=re.I)
        return "UCA-" + slug.upper().replace("_", "-")
    if m := re.search(r"AC\s*-\s*0*(\d+)", first_page):
        return f"AC-{m.group(1).zfill(3)}"
    return stem


# Masthead / boilerplate cover lines that precede the real title when a
# document has no date line (UCA guidance, ops-manual template).
MASTHEAD_RE = re.compile(
    r"^(香港特別行政區政府|民航處|Civil Aviation Department|The Government|"
    r"Small Unmanned Aircraft Advisory Circular|Advisory Circular|"
    r"for Unconventional Aircraft Trials|No\.\s|第\s*AC|第\s*\[|＜|讀者須知)"
)


def extract_title(first_page: str, metadata_title: str | None, filename: str) -> str:
    """Title = line(s) between the cover date line and the first section.

    Without a date line (some UCA documents), take the first non-masthead
    lines before the opening "1." section instead.
    """
    lines = [normalize_text(ln) for ln in first_page.splitlines()]
    lines = [ln for ln in lines if ln]
    start = next(
        (i for i, ln in enumerate(lines) if DATE_LINE_RE.search(ln)),
        None,
    )
    if start is None:
        start = -1
        while start + 1 < len(lines) and MASTHEAD_RE.match(lines[start + 1]):
            start += 1
    title_lines: list[str] = []
    for ln in lines[start + 1 :]:
        if CLAUSE_HEADING_RE.match(ln) or MASTHEAD_RE.match(ln):
            break
        title_lines.append(ln)
        if len(" ".join(title_lines)) > 120:
            break
    title = normalize_text(" ".join(title_lines))
    if title:
        return title
    if metadata_title and not re.search(r"\.docx?$|Microsoft Word", metadata_title):
        return metadata_title.strip()
    return Path(filename).stem


# --- clause blocks ------------------------------------------------------------


def split_blocks(pages: list[list[str]]) -> list[Block]:
    """Group cleaned lines into clause blocks, tracking page spans."""
    blocks: list[Block] = []
    current: Block | None = None
    for page_no, lines in enumerate(pages, start=1):
        for line in lines:
            heading = CLAUSE_HEADING_RE.match(line)
            appendix = APPENDIX_HEADING_RE.match(line)
            if heading or appendix:
                clause = heading.group(1) if heading else None
                text = line
                if appendix and not heading:
                    text = line
                    clause = normalize_text(appendix.group(0))
                current = Block(
                    clause=clause, text=text, page_start=page_no, page_end=page_no
                )
                blocks.append(current)
            elif current is None:
                current = Block(clause=None, text=line, page_start=page_no, page_end=page_no)
                blocks.append(current)
            else:
                current.text = f"{current.text} {line}"
                current.page_end = page_no
    for block in blocks:
        block.text = normalize_text(block.text)
    return [b for b in blocks if b.text]


# --- chunk packing ------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [p for p in (s.strip() for s in parts) if p]


def _pack_units(
    units: list[tuple[str, Block]],
    max_tokens: int,
    overlap_tokens: int,
    count: Callable[[str], int],
) -> list[tuple[str, list[Block]]]:
    """Greedily pack (text, origin-block) units into <= max_tokens chunks.

    Overlap: the next chunk re-opens with the previous chunk's trailing units
    up to `overlap_tokens`, so a clause split across a boundary stays whole
    in at least one chunk.
    """
    chunks: list[tuple[str, list[Block]]] = []
    cur_units: list[tuple[str, Block]] = []
    cur_tokens = 0
    for text, block in units:
        t = count(text)
        if cur_units and cur_tokens + t > max_tokens:
            chunks.append((" ".join(u for u, _ in cur_units), [b for _, b in cur_units]))
            carry: list[tuple[str, Block]] = []
            carry_tokens = 0
            for u in reversed(cur_units):
                ut = count(u[0])
                if carry and carry_tokens + ut > overlap_tokens:
                    break
                if not carry and ut > overlap_tokens:
                    break
                carry.insert(0, u)
                carry_tokens += ut
            cur_units = carry
            cur_tokens = carry_tokens
        cur_units.append((text, block))
        cur_tokens += t
    if cur_units:
        chunks.append((" ".join(u for u, _ in cur_units), [b for _, b in cur_units]))
    return chunks


def chunk_pages(
    pages: list[str],
    *,
    doc_id: str,
    doc_title: str,
    source_file: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    token_counter: Callable[[str], int] = estimate_tokens,
) -> list[Chunk]:
    """Chunk one document's raw per-page text. Pure — safe for unit tests."""
    blocks = split_blocks(clean_pages(pages))

    # Glue runts: clause-less strays fold into the previous block; bare
    # numbered headings ("1. 背景" — short, no sentence-final punctuation)
    # attach to the NEXT block so the chunk cites the substantive clause
    # (para. 1.1), not the heading. Short but punctuated clauses stay whole.
    merged: list[Block] = []
    pending: Block | None = None
    for block in blocks:
        if pending is not None:
            block = Block(
                clause=block.clause,
                text=normalize_text(f"{pending.text} {block.text}"),
                page_start=pending.page_start,
                page_end=block.page_end,
            )
            pending = None
        is_runt = token_counter(block.text) < MIN_BLOCK_TOKENS and not re.search(
            r"[。！？.!?]$", block.text
        )
        if is_runt:
            if block.clause is None and merged:
                prev = merged[-1]
                prev.text = normalize_text(f"{prev.text} {block.text}")
                prev.page_end = block.page_end
            else:
                pending = block
            continue
        merged.append(block)
    if pending is not None:
        if merged:
            prev = merged[-1]
            prev.text = normalize_text(f"{prev.text} {pending.text}")
            prev.page_end = pending.page_end
        else:
            merged.append(pending)

    # Split oversized blocks at sentence boundaries; keep (unit, origin) pairs.
    units: list[tuple[str, Block]] = []
    for block in merged:
        if token_counter(block.text) <= max_tokens:
            units.append((block.text, block))
            continue
        sentences = _split_sentences(block.text)
        buf: list[str] = []
        buf_tokens = 0
        for sent in sentences:
            st = token_counter(sent)
            if buf and buf_tokens + st > max_tokens:
                units.append((" ".join(buf), block))
                tail: list[str] = []
                tail_tokens = 0
                for s in reversed(buf):
                    s_t = token_counter(s)
                    if tail and tail_tokens + s_t > overlap_tokens:
                        break
                    tail.insert(0, s)
                    tail_tokens += s_t
                buf, buf_tokens = tail, tail_tokens
            buf.append(sent)
            buf_tokens += st
        if buf:
            units.append((" ".join(buf), block))

    packed = _pack_units(units, max_tokens, overlap_tokens, token_counter)

    full_text = " ".join(text for text, _ in packed) if packed else ""
    lang = detect_lang(full_text)
    chunks: list[Chunk] = []
    for i, (text, origins) in enumerate(packed):
        clauses = [b.clause for b in origins if b.clause]
        chunks.append(
            Chunk(
                doc_id=doc_id,
                doc_title=doc_title,
                chunk_index=i,
                text=text,
                clause=clauses[0] if clauses else None,
                page_start=min(b.page_start for b in origins),
                page_end=max(b.page_end for b in origins),
                lang=lang,
                source_file=source_file,
                extra={"clauses": ",".join(dict.fromkeys(clauses))},
            )
        )
    return chunks


def chunk_pdf(
    pdf_path: str | Path,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    token_counter: Callable[[str], int] = estimate_tokens,
) -> list[Chunk]:
    """Full pipeline for one CAD PDF: extract -> identify -> chunk."""
    from pypdf import PdfReader

    pdf_path = Path(pdf_path)
    reader = PdfReader(str(pdf_path))
    pages = [page.extract_text() or "" for page in reader.pages]
    first_page = pages[0] if pages else ""
    meta_title = (reader.metadata or {}).get("/Title")
    return chunk_pages(
        pages,
        doc_id=extract_doc_id(first_page, pdf_path.name),
        doc_title=extract_title(first_page, meta_title, pdf_path.name),
        source_file=pdf_path.name,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        token_counter=token_counter,
    )
