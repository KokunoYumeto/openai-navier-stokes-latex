#!/usr/bin/env python3
"""Build exact page and formula locators from the current transcription bytes.

An ``NSFormula`` marker controls only the display that begins immediately after
the marker (apart from whitespace).  The builder deliberately does not search
ahead: any comment, prose, command, or unrecognized display delimiter between
the marker and the formula is an error.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from audit_transcription import EXPECTED_PDF_SHA256, RANGES, ROOT, balanced_braced, range_name, read_jsonl


OUTPUT = ROOT / "evidence" / "transcription" / "PDF_TEX_CORRESPONDENCE.json"
FORMULAS = ROOT / "evidence" / "transcription" / "FORMULA_INVENTORY.json"
DISPLAY_MARKER = re.compile(r"\\NSFormula\{(NS-F-P(\d{3})-(\d{3}))\}\{display\}\{([^{}]*)\}")
INLINE_MARKER = re.compile(r"\\NSi\{(NS-F-P(\d{3})-(\d{3}))\}")
DISPLAY_BEGIN = re.compile(r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}")


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def exact_utf8_text(path: Path) -> str:
    """Decode without universal-newline conversion so formula slices stay exact."""

    payload = path.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        payload = payload[3:]
    return payload.decode("utf-8")


def find_tex_control_token(text: str, token: str, start: int, limit: int) -> int:
    """Find a TeX control token, ignoring a backslash paired by ``\\``.

    This matters for bracket displays because a row break such as ``\\\\[2pt]``
    contains the characters ``\\[`` at its second backslash but does not open a
    new display.
    """

    cursor = start
    while True:
        found = text.find(token, cursor, limit)
        if found < 0:
            return -1
        preceding_backslashes = 0
        scan = found - 1
        while scan >= 0 and text[scan] == "\\":
            preceding_backslashes += 1
            scan -= 1
        if preceding_backslashes % 2 == 0:
            return found
        cursor = found + 1


def bind_display_formula(
    text: str,
    marker_end: int,
    limit: int,
    marker_id: str,
    path: Path,
) -> tuple[str, int, str]:
    """Return the immediate display's exact bytes-as-text, end, and syntax.

    Only whitespace may occur between the marker and ``\\[`` or a supported
    top-level display environment.  Searching farther ahead would let one
    marker acquire a later formula, which is precisely the ambiguity this
    inventory must reject.
    """

    cursor = marker_end
    while cursor < limit and text[cursor].isspace():
        cursor += 1
    location = f"{path}:{line_number(text, marker_end)}"
    if cursor >= limit:
        raise RuntimeError(f"Display marker {marker_id} at {location} has no following display")

    if text.startswith(r"\[", cursor):
        close = find_tex_control_token(text, r"\]", cursor + 2, limit)
        if close < 0:
            raise RuntimeError(f"Bracket display for {marker_id} at {location} has no closing \\]")
        nested = find_tex_control_token(text, r"\[", cursor + 2, close)
        if nested >= 0:
            raise RuntimeError(f"Bracket display for {marker_id} at {location} contains an ambiguous nested \\[")
        formula_end = close + 2
        return text[cursor:formula_end], formula_end, "bracket"

    opening = DISPLAY_BEGIN.match(text, cursor, limit)
    if opening is None:
        preview = text[cursor:min(limit, cursor + 80)].replace("\r", r"\r").replace("\n", r"\n")
        raise RuntimeError(
            f"Display marker {marker_id} at {location} is not immediately followed by a recognized display; "
            f"next bytes are {preview!r}"
        )
    environment = opening.group(1)
    begin_token = opening.group(0)
    end_token = rf"\end{{{environment}}}"
    close = find_tex_control_token(text, end_token, opening.end(), limit)
    if close < 0:
        raise RuntimeError(
            f"Display environment {environment!r} for {marker_id} at {location} has no matching {end_token}"
        )
    nested = find_tex_control_token(text, begin_token, opening.end(), close)
    if nested >= 0:
        raise RuntimeError(
            f"Display environment {environment!r} for {marker_id} at {location} contains an ambiguous nested opening"
        )
    formula_end = close + len(end_token)
    return text[cursor:formula_end], formula_end, environment


def formulas_in_span(text: str, start: int, end: int, path: Path) -> list[dict]:
    records = []
    inline_matches = list(INLINE_MARKER.finditer(text, start, end))
    raw_inline_count = text.count(r"\NSi{", start, end)
    if raw_inline_count != len(inline_matches):
        raise RuntimeError(
            f"Malformed inline marker in {path}: parsed {len(inline_matches)} of {raw_inline_count} occurrences"
        )
    for match in inline_matches:
        cursor = match.end()
        while cursor < end and text[cursor].isspace():
            cursor += 1
        try:
            formula, formula_end = balanced_braced(text, cursor)
        except ValueError as exc:
            raise RuntimeError(f"Malformed inline formula {match.group(1)} in {path}: {exc}") from exc
        if formula_end > end:
            raise RuntimeError(f"Formula {match.group(1)} crosses its source-page span in {path}")
        records.append({
            "id": match.group(1), "pdf_page": int(match.group(2)), "ordinal": int(match.group(3)),
            "kind": "inline", "printed_number": None, "tex": formula,
            "tex_sha256": digest(formula.encode("utf-8")), "file": path.relative_to(ROOT).as_posix(),
            "line": line_number(text, match.start()),
        })
    display_matches = list(DISPLAY_MARKER.finditer(text, start, end))
    raw_display_count = text.count(r"\NSFormula{", start, end)
    if raw_display_count != len(display_matches):
        raise RuntimeError(
            f"Malformed display marker in {path}: parsed {len(display_matches)} of {raw_display_count} occurrences"
        )
    for match in display_matches:
        display_tex, display_end, display_syntax = bind_display_formula(
            text, match.end(), end, match.group(1), path
        )
        if display_end > end:
            raise RuntimeError(f"Display {match.group(1)} crosses its source-page span in {path}")
        records.append({
            "id": match.group(1), "pdf_page": int(match.group(2)), "ordinal": int(match.group(3)),
            "kind": "display", "printed_number": match.group(4), "display_syntax": display_syntax,
            "tex": display_tex, "tex_sha256": digest(display_tex.encode("utf-8")),
            "file": path.relative_to(ROOT).as_posix(),
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
            raise RuntimeError(f"Missing transcription or page checks for {name}")
        text = exact_utf8_text(path)
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
    formula_ids = [row["id"] for row in formula_records]
    if len(formula_ids) != len(set(formula_ids)):
        duplicates = sorted({formula_id for formula_id in formula_ids if formula_ids.count(formula_id) > 1})
        raise RuntimeError(f"Duplicate formula marker IDs: {duplicates}")
    inline_count = sum(row["kind"] == "inline" for row in formula_records)
    display_count = sum(row["kind"] == "display" for row in formula_records)
    display_syntax_counts = {
        syntax: sum(row.get("display_syntax") == syntax for row in formula_records)
        for syntax in ("bracket", "equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*")
        if any(row.get("display_syntax") == syntax for row in formula_records)
    }
    records_sha256 = digest(
        json.dumps(formula_records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    correspondence = {
        "schema": "navier-stokes-pdf-tex-correspondence/v1",
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "page_count": len(page_records),
        "coverage_complete": [row["pdf_page"] for row in page_records] == list(range(1, 167)),
        "pages": page_records,
    }
    formula_inventory = {
        "schema": "navier-stokes-formula-inventory/v2",
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "formula_count": len(formula_records),
        "inline_formula_count": inline_count,
        "display_formula_count": display_count,
        "display_syntax_counts": display_syntax_counts,
        "records_sha256": records_sha256,
        "records": formula_records,
    }
    OUTPUT.write_text(json.dumps(correspondence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    FORMULAS.write_text(json.dumps(formula_inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "pages": len(page_records),
        "coverage_complete": correspondence["coverage_complete"],
        "formulas": len(formula_records),
        "inline_formulas": inline_count,
        "display_formulas": display_count,
        "display_syntax_counts": display_syntax_counts,
        "records_sha256": records_sha256,
    }, indent=2))


if __name__ == "__main__":
    main()
