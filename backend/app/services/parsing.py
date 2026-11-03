"""PDF parsing: Docling for small docs, pypdfium2 + OCR for the main path.

Heavy libraries are imported lazily so the API can start before the optional
`parsing` extra is installed. The hybrid parser extracts the text layer page by
page and only runs OCR on pages that have no text, which keeps long documents
fast and bounded.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from app.core.config import settings
from app.models.schemas import Block, BlockKind, ParsedPaper, Reference

logger = logging.getLogger(__name__)

TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}
ProgressCallback = Callable[[str, int, int, str], None]


class ParseError(RuntimeError):
    pass


def _block(
    page: int,
    text: str,
    *,
    kind: BlockKind = BlockKind.paragraph,
    bbox: list[float] | None = None,
    bbox_space: str = "bottom-left",
    section_path: list[str] | None = None,
) -> Block:
    return Block(
        id=f"b_{uuid.uuid4().hex[:12]}",
        page=page,
        text=text,
        kind=kind,
        bbox=bbox,
        bbox_space=bbox_space,  # type: ignore[arg-type]
        section_path=section_path or [],
    )


def _kind_from_label(label: str) -> BlockKind:
    label = (label or "").lower()
    if "title" in label or "heading" in label or "section_header" in label:
        return BlockKind.heading
    if "table" in label:
        return BlockKind.table
    if "formula" in label or "equation" in label:
        return BlockKind.formula
    if "caption" in label or "figure" in label:
        return BlockKind.figure_caption
    if "reference" in label or "bibli" in label:
        return BlockKind.reference
    return BlockKind.paragraph


def _split_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    """Split a page into paragraph-ish windows so RAG can retrieve finely."""

    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(
                window.rfind("\n\n"),
                window.rfind(". "),
                window.rfind("? "),
                window.rfind("! "),
            )
            if cut > max_chars // 2:
                end = start + cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _is_heading(line: str) -> bool:
    if not 4 <= len(line) <= 90:
        return False
    if line in {
        "Abstract",
        "Introduction",
        "Conclusion",
        "References",
        "Acknowledgements",
    }:
        return True
    if re.match(r"^\d+(?:\.\d+)*\.?\s+.+\s+\d{1,3}$", line):
        # Running header such as "1.1 Supervised learning 3" (page number).
        return False
    return bool(re.match(r"^\d+(?:\.\d+)*\.?\s*[A-Z].{2,70}$", line)) and not line.endswith(".")


_REF_START = re.compile(r"^(?:\[\d+\]|\d+\.\s+[A-Z])")
_REFERENCE_END = {"appendix", "acknowledgements", "acknowledgments"}
_TOC_LEADER = re.compile(r"(?:\.\s*){4,}")


class _DocState:
    """Section state carried across pages."""

    def __init__(self) -> None:
        self.stack: list[tuple[int, str]] = []
        self.in_references = False


def _heading_depth(title: str) -> int:
    match = re.match(r"^(\d+(?:\.\d+)*)\.?\s", title.strip())
    if match:
        return match.group(1).count(".") + 1
    return 1


def _update_sections(
    stack: list[tuple[int, str]], title: str
) -> list[str]:
    depth = _heading_depth(title)
    while stack and stack[-1][0] >= depth:
        stack.pop()
    stack.append((depth, title))
    return [item for _, item in stack]


def _line_spans(text: str) -> list[tuple[str, int, int]]:
    """Return each line with its character offsets in the page text."""

    spans: list[tuple[str, int, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        raw = line.rstrip("\r\n")
        spans.append((raw, offset, offset + len(raw)))
        offset += len(line)
    return spans


def _union_charboxes(
    textpage: Any, start: int, end: int
) -> list[float] | None:
    """Union character boxes into one PDF-space bbox (bottom-left origin)."""

    limit = textpage.count_chars()
    left = bottom = float("inf")
    right = top = float("-inf")
    for index in range(max(0, start), min(end, limit)):
        try:
            x0, y0, x1, y1 = textpage.get_charbox(index)
        except Exception:
            continue
        if x1 <= x0 or y1 <= y0:
            continue
        left = min(left, x0)
        bottom = min(bottom, y0)
        right = max(right, x1)
        top = max(top, y1)
    if left == float("inf"):
        return None
    return [round(left, 2), round(bottom, 2), round(right, 2), round(top, 2)]


def _blocks_from_textpage(
    textpage: Any, page_number: int, state: _DocState
) -> list[Block]:
    """Emit blocks in reading order with bbox and heading hierarchy."""

    raw = textpage.get_text_range() or ""
    if not raw.strip():
        return []
    blocks: list[Block] = []
    stack = state.stack
    paragraphs: list[tuple[str, int, int]] = []
    references: list[tuple[str, int, int]] = []
    in_references = state.in_references
    spans = _line_spans(raw)
    is_toc = sum(1 for line, _, _ in spans if _TOC_LEADER.search(line)) >= 3

    def current_path() -> list[str]:
        return [item for _, item in stack]

    def flush_paragraph() -> None:
        nonlocal paragraphs
        if not paragraphs:
            return
        text = "\n".join(item[0] for item in paragraphs)
        bbox = _union_charboxes(
            textpage, paragraphs[0][1], paragraphs[-1][2]
        )
        path = current_path()
        for chunk in _split_text(text):
            blocks.append(
                _block(
                    page_number,
                    chunk,
                    bbox=bbox,
                    bbox_space="bottom-left",
                    section_path=path,
                )
            )
        paragraphs = []

    def flush_reference() -> None:
        nonlocal references
        if not references:
            return
        text = " ".join(item[0] for item in references)
        bbox = _union_charboxes(
            textpage, references[0][1], references[-1][2]
        )
        path = current_path()
        blocks.append(
            _block(
                page_number,
                text,
                kind=BlockKind.reference,
                bbox=bbox,
                bbox_space="bottom-left",
                section_path=path,
            )
        )
        references = []

    def add_heading(line: str, start: int, end: int) -> None:
        path = _update_sections(stack, line)
        blocks.append(
            _block(
                page_number,
                line,
                kind=BlockKind.heading,
                bbox=_union_charboxes(textpage, start, end),
                bbox_space="bottom-left",
                section_path=path,
            )
        )

    for line, start, end in spans:
        candidate = " ".join(line.split())
        if not candidate:
            continue
        if is_toc:
            paragraphs.append((candidate, start, end))
            continue
        if in_references:
            marker = candidate.strip().lower().rstrip(":")
            if marker in _REFERENCE_END:
                flush_reference()
                add_heading(candidate, start, end)
                in_references = False
                continue
            if _REF_START.match(candidate):
                flush_reference()
            references.append((candidate, start, end))
            continue
        if _is_heading(candidate):
            flush_paragraph()
            flush_reference()
            add_heading(candidate, start, end)
            if candidate.strip().lower().rstrip(":") in {
                "references",
                "bibliography",
                "参考文献",
            }:
                in_references = True
            continue
        paragraphs.append((candidate, start, end))

    flush_paragraph()
    flush_reference()
    state.in_references = in_references
    return blocks


def _blocks_for_page(
    page: Any, page_number: int, state: _DocState
) -> list[Block]:
    textpage = page.get_textpage()
    try:
        return _blocks_from_textpage(textpage, page_number, state)
    finally:
        close = getattr(textpage, "close", None)
        if callable(close):
            close()


def _parse_with_docling(path: Path) -> ParsedPaper:
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(str(path))
    document = result.document
    blocks: list[Block] = []

    try:
        data: dict[str, Any] = document.export_to_dict()
    except AttributeError:
        text = document.export_to_markdown()
        if not text.strip():
            return ParsedPaper(parse_engine="docling")
        return ParsedPaper(
            pages=1,
            blocks=[_block(1, text.strip())],
            parse_engine="docling",
        )

    for item in data.get("texts", []):
        text = (item.get("text") or "").strip()
        if not text:
            continue
        prov = (item.get("prov") or [{}])[0]
        page = int(prov.get("page_no") or 1)
        bbox_value = prov.get("bbox")
        bbox: list[float] | None = None
        if isinstance(bbox_value, dict):
            bbox = [
                float(bbox_value.get("l", 0)),
                float(bbox_value.get("t", 0)),
                float(bbox_value.get("r", 0)),
                float(bbox_value.get("b", 0)),
            ]
        elif isinstance(bbox_value, (list, tuple)) and len(bbox_value) == 4:
            bbox = [float(v) for v in bbox_value]
        blocks.append(
            _block(
                page,
                text,
                kind=_kind_from_label(str(item.get("label", ""))),
                bbox=bbox,
                bbox_space="top-left",
            )
        )

    pages = len(data.get("pages") or {}) or (max((b.page for b in blocks), default=0))
    return ParsedPaper(
        pages=pages,
        blocks=blocks,
        parse_engine="docling",
        metadata={"docling_labels": sorted({str(i.get("label")) for i in data.get("texts", [])})},
    )


def _parse_with_pypdfium2(path: Path) -> ParsedPaper:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    blocks: list[Block] = []
    state = _DocState()
    for index in range(len(pdf)):
        page = pdf[index]
        try:
            blocks.extend(_blocks_for_page(page, index + 1, state))
        finally:
            _close_page(page)
    return ParsedPaper(pages=len(pdf), blocks=blocks, parse_engine="pypdfium2")


def _restore_spaces(text: str) -> str:
    """Insert spaces into OCR output that lost them, while sparing names."""

    if len(text) < 8 or "@" in text or "http" in text.lower():
        return text
    try:
        import wordninja
    except ImportError:
        return text

    def fix(match: re.Match[str]) -> str:
        word = match.group(0)
        if len(word) < 6 or word.endswith(("*", "†", "‡")) or word.isupper():
            return word
        uppercase = sum(1 for char in word if char.isupper())
        if uppercase >= 3:
            return " ".join(wordninja.split(word))
        if uppercase == 0 and len(word) >= 8:
            return " ".join(wordninja.split(word))
        if uppercase == 1 and len(word) >= 12:
            return " ".join(wordninja.split(word))
        if uppercase == 2 and len(word) >= 20:
            return " ".join(wordninja.split(word))
        return word

    result = re.sub(r"[A-Za-z]+", fix, text)
    return re.sub(r"(?<=\d)(?=[A-Za-z])", " ", result)


def _page_text(page: Any) -> str:
    textpage = page.get_textpage()
    try:
        try:
            return textpage.get_text_bounded() or ""
        except AttributeError:
            return textpage.get_text_range() or ""
    finally:
        close = getattr(textpage, "close", None)
        if callable(close):
            close()


def _close_page(page: Any) -> None:
    close = getattr(page, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _load_ocr_engine() -> tuple[str, Any] | None:
    try:
        from rapidocr_onnxruntime import RapidOCR

        return "rapidocr", RapidOCR()
    except Exception:
        pass
    try:
        from paddleocr import PaddleOCR

        return "paddleocr", PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    except Exception:
        return None


def _ocr_blocks_from_page(
    page: Any,
    page_index: int,
    engine_name: str,
    engine: Any,
    state: _DocState,
) -> list[Block]:
    import numpy as np

    scale = 2
    height = page.get_size()[1]
    image = page.render(scale=scale).to_pil().convert("RGB")
    array = np.array(image)[:, :, ::-1]  # OpenCV/RapidOCR expects BGR
    blocks: list[Block] = []
    if engine_name == "rapidocr":
        result, _elapsed = engine(array)
        lines = [
            (item[0], _restore_spaces(str(item[1]).strip()))
            for item in (result or [])
        ]
    else:
        result = engine.ocr(array, cls=True)
        lines = [
            (line[0], _restore_spaces(str(line[1][0]).strip()))
            for line in ((result[0] if result else []) or [])
        ]
    stack = state.stack
    for box, text in lines:
        if not text:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        # OCR gives top-left pixels at `scale`×; convert to PDF points,
        # bottom-left origin, which is what the PDF.js highlight expects.
        bbox = [
            round(min(xs) / scale, 2),
            round(height - max(ys) / scale, 2),
            round(max(xs) / scale, 2),
            round(height - min(ys) / scale, 2),
        ]
        if _is_heading(text):
            kind = BlockKind.heading
            path = _update_sections(stack, text)
        else:
            kind = BlockKind.paragraph
            path = [item for _, item in stack]
        blocks.append(
            _block(
                page_index + 1,
                text,
                kind=kind,
                bbox=bbox,
                bbox_space="bottom-left",
                section_path=path,
            )
        )
    return blocks


def _parse_hybrid(
    pdf: Any,
    path: Path,
    progress: ProgressCallback | None,
    ocr_max_pages: int,
) -> ParsedPaper:
    """Text pages via pypdfium2; OCR only pages that have no text layer."""

    total = len(pdf)
    blocks: list[Block] = []
    ocr_indices: list[int] = []
    text_pages = 0
    state = _DocState()
    for index in range(total):
        page = pdf[index]
        try:
            page_blocks = _blocks_for_page(page, index + 1, state)
        finally:
            _close_page(page)
        if page_blocks:
            text_pages += 1
            blocks.extend(page_blocks)
        else:
            ocr_indices.append(index)
        if progress:
            progress("extract", index + 1, total, f"提取文本 {index + 1}/{total} 页")

    ocr_pages = 0
    skipped = 0
    ocr_engine_name = "rapidocr"
    if ocr_indices:
        loaded = _load_ocr_engine()
        if loaded is None:
            skipped = len(ocr_indices)
        else:
            ocr_engine_name, engine = loaded
            limit = (
                len(ocr_indices)
                if ocr_max_pages <= 0
                else min(len(ocr_indices), ocr_max_pages)
            )
            for position, page_index in enumerate(ocr_indices[:limit], start=1):
                page = pdf[page_index]
                try:
                    blocks.extend(
                        _ocr_blocks_from_page(
                            page, page_index, ocr_engine_name, engine, state
                        )
                    )
                finally:
                    _close_page(page)
                ocr_pages += 1
                if progress:
                    progress(
                        "ocr",
                        position,
                        limit,
                        f"OCR {page_index + 1}/{total} 页",
                    )
            skipped = len(ocr_indices) - limit

    meta_title = ""
    try:
        meta_title = (pdf.get_metadata_dict() or {}).get("Title") or ""
    except Exception:
        pass
    metadata = {
        "text_pages": text_pages,
        "ocr_pages": ocr_pages,
        "ocr_skipped_pages": skipped,
    }
    if len(str(meta_title).strip()) >= 8:
        metadata["title"] = str(meta_title).strip()[:220]

    return ParsedPaper(
        pages=total,
        blocks=blocks,
        parse_engine=(
            f"pypdfium2+{ocr_engine_name}" if ocr_pages else "pypdfium2"
        ),
        metadata=metadata,
    )


def _parse_with_rapidocr(path: Path) -> ParsedPaper:
    """Local OCR fallback for image-only PDFs (no system install needed)."""

    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR

    pdf = pdfium.PdfDocument(str(path))
    engine = RapidOCR()
    blocks: list[Block] = []
    for index in range(len(pdf)):
        image = pdf[index].render(scale=2).to_pil().convert("RGB")
        array = np.array(image)[:, :, ::-1]  # RapidOCR/OpenCV expects BGR
        result, _elapsed = engine(array)
        for item in result or []:
            box = item[0]
            text = _restore_spaces(str(item[1]).strip())
            if not text:
                continue
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            kind = BlockKind.heading if _is_heading(text) else BlockKind.paragraph
            blocks.append(
                _block(
                    index + 1,
                    text,
                    kind=kind,
                    bbox=[min(xs), min(ys), max(xs), max(ys)],
                    bbox_space="top-left",
                )
            )
    return ParsedPaper(pages=len(pdf), blocks=blocks, parse_engine="rapidocr")


def _parse_with_paddleocr(path: Path) -> ParsedPaper:
    import numpy as np
    import pypdfium2 as pdfium
    from paddleocr import PaddleOCR

    pdf = pdfium.PdfDocument(str(path))
    ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    blocks: list[Block] = []
    for index in range(len(pdf)):
        page = pdf[index]
        image = page.render(scale=2).to_pil()
        result = ocr.ocr(np.array(image), cls=True)
        lines = result[0] if result else []
        for line in lines or []:
            points = line[0]
            text, _score = line[1]
            text = (text or "").strip()
            if not text:
                continue
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            blocks.append(
                _block(
                    index + 1,
                    text,
                    bbox=[min(xs), min(ys), max(xs), max(ys)],
                    bbox_space="top-left",
                )
            )
    return ParsedPaper(pages=len(pdf), blocks=blocks, parse_engine="paddleocr")


_grobid_unavailable = False


def extract_references(
    path: str | Path,
    grobid_url: str | None = None,
    max_tail_pages: int = 0,
) -> list[Reference]:
    global _grobid_unavailable
    path = Path(path)
    references: list[Reference] = []
    if not _grobid_unavailable:
        try:
            references = _extract_with_grobid(
                path, grobid_url or settings.grobid_url
            )
        except Exception as exc:
            _grobid_unavailable = True
            logger.warning(
                "GROBID reference extraction unavailable: %s", exc
            )
    if references:
        return references
    try:
        return _extract_references_from_text(path, max_tail_pages=max_tail_pages)
    except Exception as exc:
        logger.warning("Fallback reference extraction failed: %s", exc)
        return []


def _extract_with_grobid(path: Path, grobid_url: str) -> list[Reference]:
    with path.open("rb") as handle:
        response = httpx.post(
            f"{grobid_url.rstrip('/')}/api/processReferences",
            files={"input": (path.name, handle, "application/pdf")},
            timeout=90,
        )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    references: list[Reference] = []
    for bibl in root.findall(".//tei:biblStruct", TEI_NS):
        title_el = bibl.find(".//tei:title", TEI_NS)
        title = " ".join(title_el.itertext()).strip() if title_el is not None else None
        authors = [
            " ".join(person.itertext()).strip()
            for person in bibl.findall(".//tei:persName", TEI_NS)
        ]
        year_el = bibl.find(".//tei:date", TEI_NS)
        year = None
        if year_el is not None:
            when = year_el.get("when") or "".join(year_el.itertext())
            match = re.search(r"\d{4}", when)
            year = int(match.group()) if match else None
        doi_el = bibl.find(".//tei:idno[@type='DOI']", TEI_NS)
        doi = "".join(doi_el.itertext()).strip() if doi_el is not None else None
        raw = " ".join(" ".join(bibl.itertext()).split())
        references.append(
            Reference(
                id=f"r_{uuid.uuid4().hex[:10]}",
                title=title or raw[:240],
                authors=authors,
                year=year,
                doi=doi,
                raw=raw,
            )
        )
    return references


def _guess_title(entry: str) -> str:
    """Pull a title out of a raw bibliography entry for graph labels."""

    text = re.sub(r"^\[\d+\]\s*", "", entry).strip()
    parts = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", text)
        if part.strip()
    ]
    if len(parts) > 1:
        def score(part: str) -> tuple[bool, bool, int]:
            words = part.split()
            return (
                part.count(",") == 0,
                3 <= len(words) <= 30,
                len(part),
            )

        best = max(parts[1:], key=score)
        if len(best) >= 8:
            return best[:240]
    return text[:240]


def _extract_references_from_text(
    path: Path, max_tail_pages: int = 0
) -> list[Reference]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    chunks: list[str] = []
    start = max(0, len(pdf) - max_tail_pages) if max_tail_pages > 0 else 0
    for index in range(start, len(pdf)):
        page = pdf[index]
        try:
            chunks.append(_page_text(page))
        finally:
            _close_page(page)
    close = getattr(pdf, "close", None)
    if callable(close):
        close()
    full_text = "\n".join(chunks)
    match = re.search(r"(?:^|\n)\s*(References|REFERENCES|Bibliography|参考文献)\s*\n", full_text)
    if not match:
        return []
    tail = full_text[match.end() :].replace("\r\n", "\n")
    parts = [
        " ".join(part.split())
        for part in re.split(r"(?=\[\d+\])", tail)
        if part.strip()
    ]
    entries = [part for part in parts if len(part) >= 20]
    if len(entries) < 3:
        entries = [
            line.strip()
            for line in tail.splitlines()
            if len(line.strip()) >= 20
        ]
    references: list[Reference] = []
    for entry in entries[:120]:
        references.append(
            Reference(
                id=f"r_{uuid.uuid4().hex[:10]}",
                title=_guess_title(entry),
                raw=entry,
            )
        )
    return references


def parse_pdf(
    path: str | Path,
    progress: ProgressCallback | None = None,
    ocr_max_pages: int | None = None,
) -> ParsedPaper:
    """Parse page by page; OCR only pages without a text layer."""

    path = Path(path)
    ocr_limit = settings.ocr_max_pages if ocr_max_pages is None else ocr_max_pages
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:
        try:
            parsed = _parse_with_docling(path)
        except Exception as docling_exc:
            raise ParseError(
                f"pypdfium2: {exc}; docling: {docling_exc}"
            ) from exc
        parsed.references = extract_references(path)
        return parsed

    try:
        total = len(pdf)
        if total <= settings.docling_max_pages:
            try:
                parsed = _parse_with_docling(path)
                if parsed.blocks:
                    parsed.references = extract_references(path)
                    return parsed
            except Exception as exc:
                logger.info("Docling unavailable/failed: %s", exc)
        if progress:
            progress("extract", 0, total, f"已打开 PDF，共 {total} 页")
        parsed = _parse_hybrid(pdf, path, progress, ocr_limit)
        if not parsed.blocks:
            raise ParseError("没有提取到文本；扫描件需要安装 RapidOCR/PaddleOCR")
        parsed.references = extract_references(
            path, max_tail_pages=60 if total > 100 else 0
        )
        return parsed
    finally:
        close = getattr(pdf, "close", None)
        if callable(close):
            close()
