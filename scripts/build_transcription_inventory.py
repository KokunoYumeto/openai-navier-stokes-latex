#!/usr/bin/env python3
"""Build exact page and formula locators from the current transcription bytes."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from audit_transcription import EXPECTED_PDF_SHA256, RANGES, ROOT, balanced_braced, range_name, read_jsonl


OUTPUT = ROOT / "evidence" / "transcription" / "PDF_TEX_CORRESPONDENCE.json"
FORMULAS = ROOT / "evidence" / "transcription" / "FORMULA_INVENTORY.json"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def formulas_in_span(text: str, start: int, end: int, path: Path) -> list[dict]:
    records = []
    inline = re.compile(r"\\NSi\{(NS-F-P(\d{3})-(\d{3}))\}")
    for match in inline.finditer(text, start, end):
        cursor = match.end()
        while cursor < end and text[cursor].isspace():
            cursor += 1
        formula, formula_end = balanced_braced(text, cursor)
        if formula_end > end:
            raise RuntimeError(f"Formula {match.group(1)} crosses its source-page span in {path}")
        records.append({
            "id": match.group(1), "pdf_page": int(match.group(2)), "ordinal": int(match.group(3)),
            "kind": "inline", "printed_number": None, "tex": formula,
            "tex_sha256": digest(formula.encode("utf-8")), "file": path.relative_to(ROOT).as_posix(),
            "line": line_number(text, match.start()),
        })
    display = re.compile(r"\\NSFormula\{(NS-F-P(\d{3})-(\d{3}))\}\{display\}\{([^{}]*)\}")
    for match in display.finditer(text, start, end):
        tail = text[match.end():end]
        env = re.search(r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}", tail)
        env_tex = None
        if env:
            begin = match.end() + env.start()
            closing = re.search(rf"\\end\{{{re.escape(env.group(1))}\}}", text[begin:end])
            if closing:
                close_end = begin + closing.end()
                env_tex = text[begin:close_end]
        records.append({
            "id": match.group(1), "pdf_page": int(match.group(2)), "ordinal": int(match.group(3)),
            "kind": "display", "printed_number": match.group(4), "tex": env_tex,
            "tex_sha256": digest((env_tex or "").encode("utf-8")), "file": path.relative_to(ROOT).as_posix(),
            "line": line_number(text, match.start()),
        })
    return sorted(records, key=lambda row: row["ordinal"])


def main() -> None:
    page_records = []
    formula_records = []
    for first, last in RANGES:
        name = range_name(first, last)
        path = ROOT / "reconstruction" / "sections" / f"{name}.tex"
        checks_path = ROOT / "evidence" / "transcription" / name / "PAGE_CHECKS.jsonl"
        if not path.is_file() or not checks_path.is_file():
            continue
        text = path.read_text(encoding="utf-8-sig")
        matches = list(re.finditer(r"\\NSPage\{(\d{3})\}", text))
        checks = {row["pdf_page"]: row for row in read_jsonl(checks_path)}
        for index, match in enumerate(matches):
            page = int(match.group(1))
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            span = text[match.start():end]
            formulas = formulas_in_span(text, match.start(), end, path)
            formula_records.extend(formulas)
            page_text = ROOT / "sources" / "official" / "paper" / "extracted" / "pages" / f"page-{page:03d}.txt"
            render = ROOT / "sources" / "official" / "paper" / "renders" / "180dpi" / f"page-{page:03d}.png"
            page_records.append({
                "id": f"NS-PAGE-{page:03d}", "pdf_page": page, "pdf_sha256": EXPECTED_PDF_SHA256,
                "pdf_text_draft": {"path": page_text.relative_to(ROOT).as_posix(), "sha256": digest(page_text.read_bytes())},
                "page_render": {"path": render.relative_to(ROOT).as_posix(), "bytes": render.stat().st_size, "sha256": digest(render.read_bytes()), "dpi": 180},
                "tex": {"path": path.relative_to(ROOT).as_posix(), "file_sha256": digest(path.read_bytes()),
                        "start_line": line_number(text, match.start()), "end_line": line_number(text, end),
                        "span_sha256": digest(span.encode("utf-8"))},
                "formula_ids": [row["id"] for row in formulas],
                "page_check": checks.get(page),
                "page_check_ledger": checks_path.relative_to(ROOT).as_posix(),
            })

    page_records.sort(key=lambda row: row["pdf_page"])
    formula_records.sort(key=lambda row: (row["pdf_page"], row["ordinal"]))
    correspondence = {
        "schema": "navier-stokes-pdf-tex-correspondence/v1",
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "page_count": len(page_records),
        "coverage_complete": [row["pdf_page"] for row in page_records] == list(range(1, 167)),
        "pages": page_records,
    }
    formula_inventory = {
        "schema": "navier-stokes-formula-inventory/v1",
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "formula_count": len(formula_records),
        "records": formula_records,
    }
    OUTPUT.write_text(json.dumps(correspondence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    FORMULAS.write_text(json.dumps(formula_inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"pages": len(page_records), "coverage_complete": correspondence["coverage_complete"], "formulas": len(formula_records)}, indent=2))


if __name__ == "__main__":
    main()
