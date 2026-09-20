#!/usr/bin/env python3
"""Fail-closed structural audit for the complete PDF-to-LaTeX transcription."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "sources" / "official" / "paper" / "navier-stokes.pdf"
EXPECTED_PDF_SHA256 = "0e779481c4da40bd28d1e642e1d8ca57447d129610df28dfa5a11e9af8ae228f"
EXPECTED_PAGES = tuple(range(1, 167))
# Six-page units keep each visual/formula audit bounded and make page-level
# progress durable.  The final four pages are split around the already checked
# bibliography fragment.
RANGES = tuple((first, first + 5) for first in range(1, 163, 6)) + (
    (163, 164),
    (165, 166),
)
RECEIPT = ROOT / "evidence" / "transcription" / "TRANSCRIPTION_AUDIT.json"
RAW_SPACING_CONTROL_WORD = re.compile(r"(?<![\\A-Za-z])q(?:q)?uad(?![A-Za-z])")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def range_name(first: int, last: int) -> str:
    return f"pp{first:03d}-{last:03d}"


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSONL at {path}:{number}: {exc}") from exc
        if not isinstance(row, dict):
            raise RuntimeError(f"Non-object JSONL row at {path}:{number}")
        rows.append(row)
    return rows


def balanced_braced(text: str, opening: int) -> tuple[str, int]:
    if opening >= len(text) or text[opening] != "{":
        raise ValueError("Expected opening brace")
    depth = 0
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1:index], index + 1
    raise ValueError("Unclosed braced argument")


def inline_formula_records(text: str, file: Path) -> list[dict]:
    records = []
    pattern = re.compile(r"\\NSi\{(NS-F-P(\d{3})-(\d{3}))\}")
    for match in pattern.finditer(text):
        cursor = match.end()
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        try:
            formula, end = balanced_braced(text, cursor)
        except ValueError as exc:
            raise RuntimeError(f"Malformed inline formula {match.group(1)} in {file}: {exc}") from exc
        records.append(
            {
                "id": match.group(1),
                "page": int(match.group(2)),
                "ordinal": int(match.group(3)),
                "kind": "inline",
                "printed_number": None,
                "tex": formula,
                "line": text.count("\n", 0, match.start()) + 1,
                "offset": match.start(),
                "end_offset": end,
            }
        )
    return records


def display_formula_records(text: str, file: Path) -> list[dict]:
    records = []
    pattern = re.compile(r"\\NSFormula\{(NS-F-P(\d{3})-(\d{3}))\}\{display\}\{([^{}]*)\}")
    for match in pattern.finditer(text):
        records.append(
            {
                "id": match.group(1),
                "page": int(match.group(2)),
                "ordinal": int(match.group(3)),
                "kind": "display",
                "printed_number": match.group(4),
                "tex": None,
                "line": text.count("\n", 0, match.start()) + 1,
                "offset": match.start(),
            }
        )
    raw_count = text.count("\\NSFormula{")
    if raw_count != len(records):
        raise RuntimeError(f"Malformed display marker in {file}: parsed {len(records)} of {raw_count}")
    return records


def main() -> None:
    issues: list[dict] = []
    pending: list[dict] = []
    files = []
    combined_parts = []
    page_markers: list[int] = []
    formulas: list[dict] = []
    page_checks: dict[int, dict] = {}
    check_paths: dict[int, str] = {}

    if not PDF.is_file() or sha256(PDF) != EXPECTED_PDF_SHA256:
        issues.append({"type": "pdf-authority", "message": "Frozen PDF is missing or has stale bytes."})

    for page in EXPECTED_PAGES:
        text_path = ROOT / "sources" / "official" / "paper" / "extracted" / "pages" / f"page-{page:03d}.txt"
        image_path = ROOT / "sources" / "official" / "paper" / "renders" / "180dpi" / f"page-{page:03d}.png"
        if not text_path.is_file():
            issues.append({"type": "missing-page-text", "page": page, "path": str(text_path)})
        if not image_path.is_file():
            issues.append({"type": "missing-page-render", "page": page, "path": str(image_path)})

    for first, last in RANGES:
        name = range_name(first, last)
        tex_path = ROOT / "reconstruction" / "sections" / f"{name}.tex"
        checks_path = ROOT / "evidence" / "transcription" / name / "PAGE_CHECKS.jsonl"
        uncertainty_path = ROOT / "evidence" / "transcription" / name / "UNCERTAINTIES.jsonl"
        report_path = ROOT / "evidence" / "transcription" / name / "REPORT.md"
        required = (tex_path, checks_path, uncertainty_path, report_path)
        missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
        if missing:
            pending.append({"range": name, "missing": missing})
            continue
        text = tex_path.read_text(encoding="utf-8-sig")
        for match in RAW_SPACING_CONTROL_WORD.finditer(text):
            issues.append(
                {
                    "type": "raw-tex-spacing-control-word",
                    "range": name,
                    "token": match.group(0),
                    "line": text.count("\n", 0, match.start()) + 1,
                    "message": "Possible missing backslash before a TeX spacing command.",
                }
            )
        markers = [int(value) for value in re.findall(r"\\NSPage\{(\d{3})\}", text)]
        expected = list(range(first, last + 1))
        if markers != expected:
            issues.append({"type": "page-marker-order", "range": name, "expected": expected, "observed": markers})
        page_markers.extend(markers)
        try:
            found_formulas = inline_formula_records(text, tex_path) + display_formula_records(text, tex_path)
        except RuntimeError as exc:
            issues.append({"type": "formula-marker-parse", "range": name, "message": str(exc)})
            found_formulas = []
        page_spans = []
        page_matches = list(re.finditer(r"\\NSPage\{(\d{3})\}", text))
        for index, page_match in enumerate(page_matches):
            span_end = page_matches[index + 1].start() if index + 1 < len(page_matches) else len(text)
            page_spans.append((page_match.start(), span_end, int(page_match.group(1))))
        for record in found_formulas:
            record["file"] = tex_path.relative_to(ROOT).as_posix()
            containing = [page for start, end, page in page_spans if start <= record["offset"] < end]
            if len(containing) != 1 or containing[0] != record["page"]:
                issues.append({
                    "type": "formula-page-placement",
                    "range": name,
                    "id": record["id"],
                    "declared_page": record["page"],
                    "containing_page": containing[0] if len(containing) == 1 else None,
                    "line": record["line"],
                })
        formulas.extend(found_formulas)
        combined_parts.append(text)
        files.append({"range": name, "path": tex_path.relative_to(ROOT).as_posix(), "bytes": tex_path.stat().st_size, "sha256": sha256(tex_path)})

        try:
            checks = read_jsonl(checks_path)
        except RuntimeError as exc:
            issues.append({"type": "page-check-jsonl", "range": name, "message": str(exc)})
            checks = []
        observed_check_pages = [row.get("pdf_page") for row in checks]
        if observed_check_pages != expected:
            issues.append({"type": "page-check-order", "range": name, "expected": expected, "observed": observed_check_pages})
        for row in checks:
            page = row.get("pdf_page")
            if not isinstance(page, int) or page in page_checks:
                issues.append({"type": "page-check-duplicate-or-invalid", "range": name, "page": page})
                continue
            page_checks[page] = row
            check_paths[page] = checks_path.relative_to(ROOT).as_posix()
            if row.get("pdf_sha256") != EXPECTED_PDF_SHA256:
                issues.append({"type": "page-check-pdf-hash", "page": page})
            for field in ("visual_inspection", "text_order", "formula_visual_check"):
                if row.get(field) != "pass":
                    issues.append({"type": "page-check-not-pass", "page": page, "field": field, "value": row.get(field)})
            uncertainty_ids = row.get("uncertainty_ids")
            if not isinstance(uncertainty_ids, list):
                issues.append({"type": "page-check-uncertainties", "page": page, "value": uncertainty_ids})

        try:
            uncertainty_rows = read_jsonl(uncertainty_path)
        except RuntimeError as exc:
            issues.append({"type": "uncertainty-jsonl", "range": name, "message": str(exc)})
            uncertainty_rows = []
        uncertainty_ids = [row.get("id") for row in uncertainty_rows]
        if any(not isinstance(value, str) or not value for value in uncertainty_ids):
            issues.append({"type": "uncertainty-id", "range": name})
        referenced_uncertainties = [value for row in checks for value in row.get("uncertainty_ids", []) if isinstance(value, str)]
        if sorted(uncertainty_ids) != sorted(referenced_uncertainties):
            issues.append({"type": "uncertainty-coverage", "range": name, "ledger": uncertainty_ids, "page_checks": referenced_uncertainties})

    if not pending and page_markers != list(EXPECTED_PAGES):
        issues.append({"type": "global-page-marker-order", "expected_count": 166, "observed": page_markers})

    formula_ids = [record["id"] for record in formulas]
    duplicate_formula_ids = sorted(identifier for identifier, count in Counter(formula_ids).items() if count != 1)
    if duplicate_formula_ids:
        issues.append({"type": "duplicate-formula-id", "ids": duplicate_formula_ids})
    formula_counts = Counter(record["page"] for record in formulas)
    formula_ordinals: defaultdict[int, list[int]] = defaultdict(list)
    for record in formulas:
        formula_ordinals[record["page"]].append(record["ordinal"])
    for page, ordinals in sorted(formula_ordinals.items()):
        if sorted(ordinals) != list(range(1, len(ordinals) + 1)):
            issues.append({"type": "formula-ordinal-gap", "page": page, "observed": sorted(ordinals)})
    for page, row in sorted(page_checks.items()):
        if row.get("formula_count") != formula_counts[page]:
            issues.append({"type": "formula-count", "page": page, "ledger": row.get("formula_count"), "markers": formula_counts[page]})

    combined = "\n".join(combined_parts)
    labels = re.findall(r"\\label\{([^{}]+)\}", combined)
    duplicate_labels = sorted(label for label, count in Counter(labels).items() if count != 1)
    if duplicate_labels:
        issues.append({"type": "duplicate-label", "labels": duplicate_labels})
    references = re.findall(r"\\(?:ref|eqref|cref|Cref)\{([^{}]+)\}", combined)
    unresolved = sorted(set(references) - set(labels))
    if not pending and unresolved:
        issues.append({"type": "unresolved-reference", "labels": unresolved})

    if not pending:
        if len(re.findall(r"\\bibitem\{ref-\d+\}", combined)) != 22:
            issues.append({"type": "bibliography-count", "expected": 22})
        for environment in ("proof", "theorem", "proposition", "lemma", "corollary", "definition", "remark", "align", "equation", "gather", "multline"):
            begins = len(re.findall(rf"\\begin\{{{environment}\*?\}}", combined))
            ends = len(re.findall(rf"\\end\{{{environment}\*?\}}", combined))
            if begins != ends:
                issues.append({"type": "environment-balance", "environment": environment, "begin": begins, "end": ends})

    status = "fail" if issues else ("pending" if pending else "pass")
    receipt = {
        "schema": "navier-stokes-transcription-audit/v1",
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "status": status,
        "expected_pages": 166,
        "completed_ranges": [record["range"] for record in files],
        "pending_ranges": pending,
        "page_markers": len(page_markers),
        "page_checks": len(page_checks),
        "formula_markers": len(formulas),
        "labels": len(labels),
        "references": len(references),
        "unresolved_references": unresolved,
        "files": files,
        "issues": issues,
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: receipt[key] for key in ("status", "completed_ranges", "pending_ranges", "page_markers", "page_checks", "formula_markers", "issues")}, ensure_ascii=False, indent=2))
    if status == "fail":
        raise SystemExit(1)
    if status == "pending":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
