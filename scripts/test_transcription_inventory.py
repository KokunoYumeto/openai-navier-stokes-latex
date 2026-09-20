#!/usr/bin/env python3
"""Regression tests and an independent audit for the formula inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from audit_transcription import EXPECTED_PDF_SHA256, RANGES, ROOT, range_name
from build_transcription_inventory import bind_display_formula


INVENTORY = ROOT / "evidence" / "transcription" / "FORMULA_INVENTORY.json"
RECEIPT = ROOT / "evidence" / "transcription" / "FORMULA_INVENTORY_AUDIT.json"
REPORT = ROOT / "evidence" / "transcription" / "FORMULA_INVENTORY_REPORT.md"
INLINE_MARKER = re.compile(r"\\NSi\{(NS-F-P(\d{3})-(\d{3}))\}")
DISPLAY_MARKER = re.compile(r"\\NSFormula\{(NS-F-P(\d{3})-(\d{3}))\}\{display\}\{([^{}]*)\}")
ENVIRONMENT_OPEN = re.compile(r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def exact_utf8_text(path: Path) -> str:
    payload = path.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        payload = payload[3:]
    return payload.decode("utf-8")


def independent_control_token(text: str, token: str, start: int, limit: int) -> int:
    """Locate an unpaired TeX control token with a scanner separate from the builder."""

    for index in range(start, max(start, limit - len(token) + 1)):
        if not text.startswith(token, index):
            continue
        slash_count = 0
        cursor = index - 1
        while cursor >= 0 and text[cursor] == "\\":
            slash_count += 1
            cursor -= 1
        if slash_count % 2 == 0:
            return index
    return -1


def independent_display(text: str, marker_end: int, limit: int) -> tuple[str, str]:
    cursor = marker_end
    while cursor < limit and text[cursor].isspace():
        cursor += 1
    if text.startswith(r"\[", cursor):
        close = independent_control_token(text, r"\]", cursor + 2, limit)
        check(close >= 0, "independent scanner found an unclosed bracket display")
        nested = independent_control_token(text, r"\[", cursor + 2, close)
        check(nested < 0, "independent scanner found a nested bracket display")
        return text[cursor:close + 2], "bracket"
    opening = ENVIRONMENT_OPEN.match(text, cursor, limit)
    check(opening is not None, "independent scanner found intervening or unrecognized content")
    environment = opening.group(1)
    close_token = rf"\end{{{environment}}}"
    close = independent_control_token(text, close_token, opening.end(), limit)
    check(close >= 0, f"independent scanner found no close for {environment}")
    nested = independent_control_token(text, opening.group(0), opening.end(), close)
    check(nested < 0, f"independent scanner found nested {environment}")
    return text[cursor:close + len(close_token)], environment


def independent_braced_body(text: str, opening: int, limit: int) -> tuple[str, int]:
    check(opening < limit and text[opening] == "{", "inline marker has no immediate braced body")
    depth = 0
    cursor = opening
    while cursor < limit:
        char = text[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1:cursor], cursor + 1
        cursor += 1
    raise AssertionError("inline marker has an unclosed braced body")


def assert_display_fixture(syntax: str, display: str) -> None:
    marker = r"\NSFormula{NS-F-P001-001}{display}{none}"
    text = marker + "\n  " + display + "\n"
    observed, end, observed_syntax = bind_display_formula(
        text, len(marker), len(text), "NS-F-P001-001", Path("fixture.tex")
    )
    check(observed == display, f"{syntax} fixture bytes changed")
    check(observed_syntax == syntax, f"{syntax} fixture was classified as {observed_syntax}")
    check(end == len(marker) + 3 + len(display), f"{syntax} fixture end offset is wrong")


def run_regressions() -> None:
    assert_display_fixture("bracket", "\\[\na&=b\\\\[2pt]\nc&=d.\n\\]")
    assert_display_fixture("equation", "\\begin{equation}\nx=1.\n\\end{equation}")
    assert_display_fixture("align", "\\begin{align}\nx&=1,\\\\\ny&=2.\n\\end{align}")
    assert_display_fixture("gather*", "\\begin{gather*}\nx=1,\\\\\ny=2.\n\\end{gather*}")

    marker = r"\NSFormula{NS-F-P001-001}{display}{none}"
    bad_cases = {
        "intervening prose": marker + "\nprose\n\\[x=1\\]",
        "intervening comment": marker + "\n% comment\n\\[x=1\\]",
        "missing display": marker + "\n",
        "missing bracket close": marker + "\n\\[x=1",
        "missing environment close": marker + "\n\\begin{equation}x=1",
    }
    for label, text in bad_cases.items():
        try:
            bind_display_formula(text, len(marker), len(text), "NS-F-P001-001", Path("fixture.tex"))
        except RuntimeError:
            continue
        raise AssertionError(f"bad association fixture did not fail: {label}")


def sequence_hash(records: list[dict]) -> str:
    digest = hashlib.sha256()
    for record in records:
        for payload in (
            record["id"].encode("utf-8"),
            record["kind"].encode("utf-8"),
            record["tex"].encode("utf-8"),
        ):
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
    return digest.hexdigest()


def audit_current_inventory() -> dict:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    check(inventory.get("schema") == "navier-stokes-formula-inventory/v2", "inventory schema is not v2")
    check(inventory.get("pdf_sha256") == EXPECTED_PDF_SHA256, "inventory names the wrong PDF bytes")
    records = inventory.get("records")
    check(isinstance(records, list), "inventory records are missing")
    by_id = {record.get("id"): record for record in records}
    check(len(by_id) == len(records), "inventory has duplicate or missing IDs")

    independent_records: list[dict] = []
    source_files: list[dict] = []
    for first, last in RANGES:
        name = range_name(first, last)
        path = ROOT / "reconstruction" / "sections" / f"{name}.tex"
        text = exact_utf8_text(path)
        relative = path.relative_to(ROOT).as_posix()
        source_files.append({
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256_bytes(path.read_bytes()),
        })
        pages = list(re.finditer(r"\\NSPage\{(\d{3})\}", text))
        check([int(item.group(1)) for item in pages] == list(range(first, last + 1)), f"page order failed in {relative}")
        spans = [
            (page.start(), pages[index + 1].start() if index + 1 < len(pages) else len(text), int(page.group(1)))
            for index, page in enumerate(pages)
        ]

        inline_matches = list(INLINE_MARKER.finditer(text))
        display_matches = list(DISPLAY_MARKER.finditer(text))
        check(len(inline_matches) == text.count(r"\NSi{"), f"malformed inline marker in {relative}")
        check(len(display_matches) == text.count(r"\NSFormula{"), f"malformed display marker in {relative}")

        for match in inline_matches:
            cursor = match.end()
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            formula, formula_end = independent_braced_body(text, cursor, len(text))
            containing = [page for start, end, page in spans if start <= match.start() < end]
            check(containing == [int(match.group(2))], f"inline page mismatch for {match.group(1)}")
            check(formula_end <= next(end for start, end, page in spans if page == containing[0]), f"inline formula crosses page for {match.group(1)}")
            independent_records.append({
                "id": match.group(1),
                "pdf_page": int(match.group(2)),
                "ordinal": int(match.group(3)),
                "kind": "inline",
                "printed_number": None,
                "tex": formula,
                "tex_sha256": sha256_bytes(formula.encode("utf-8")),
                "file": relative,
                "line": text.count("\n", 0, match.start()) + 1,
            })

        for match in display_matches:
            containing = [page for start, end, page in spans if start <= match.start() < end]
            check(containing == [int(match.group(2))], f"display page mismatch for {match.group(1)}")
            page_end = next(end for start, end, page in spans if page == containing[0])
            formula, syntax = independent_display(text, match.end(), page_end)
            independent_records.append({
                "id": match.group(1),
                "pdf_page": int(match.group(2)),
                "ordinal": int(match.group(3)),
                "kind": "display",
                "printed_number": match.group(4),
                "display_syntax": syntax,
                "tex": formula,
                "tex_sha256": sha256_bytes(formula.encode("utf-8")),
                "file": relative,
                "line": text.count("\n", 0, match.start()) + 1,
            })

    independent_records.sort(key=lambda record: (record["pdf_page"], record["ordinal"]))
    check(records == independent_records, "inventory differs from the independent source parse")
    canonical_records = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    records_sha256 = sha256_bytes(canonical_records)
    check(inventory.get("records_sha256") == records_sha256, "records_sha256 does not match the record bytes")

    kind_counts = Counter(record["kind"] for record in records)
    syntax_counts = Counter(record.get("display_syntax") for record in records if record["kind"] == "display")
    expected_syntax = {
        "bracket": 370,
        "equation": 360,
        "equation*": 19,
        "align": 2,
        "align*": 14,
        "gather*": 2,
    }
    check(len(records) == 6175, f"expected 6175 formulas, found {len(records)}")
    check(kind_counts == {"inline": 5408, "display": 767}, f"formula kind counts differ: {dict(kind_counts)}")
    check(dict(syntax_counts) == expected_syntax, f"display syntax counts differ: {dict(syntax_counts)}")
    check(inventory.get("formula_count") == 6175, "formula_count differs")
    check(inventory.get("inline_formula_count") == 5408, "inline_formula_count differs")
    check(inventory.get("display_formula_count") == 767, "display_formula_count differs")
    check(inventory.get("display_syntax_counts") == expected_syntax, "top-level display syntax counts differ")
    check(all(record["tex"] for record in records), "at least one formula has empty TeX")
    check(all(record["tex_sha256"] == sha256_bytes(record["tex"].encode("utf-8")) for record in records), "a formula hash differs")

    source_file_set_sha256 = sha256_bytes(
        json.dumps(source_files, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    return {
        "schema": "navier-stokes-formula-inventory-audit/v1",
        "status": "pass",
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "formula_inventory": {
            "path": INVENTORY.relative_to(ROOT).as_posix(),
            "bytes": INVENTORY.stat().st_size,
            "sha256": sha256_bytes(INVENTORY.read_bytes()),
            "schema": inventory["schema"],
            "records_sha256": records_sha256,
            "formula_sequence_sha256": sequence_hash(records),
        },
        "source_files": {
            "count": len(source_files),
            "set_sha256": source_file_set_sha256,
            "records": source_files,
        },
        "counts": {
            "pages": 166,
            "formulas": len(records),
            "inline": kind_counts["inline"],
            "display": kind_counts["display"],
            "display_syntax": expected_syntax,
            "formula_tex_utf8_bytes": sum(len(record["tex"].encode("utf-8")) for record in records),
        },
        "checks": [
            {"check": "fixture regressions for bracket, equation, align, gather, bad, and missing associations", "result": "pass"},
            {"check": "every marker is on its declared page and has one immediate formula", "result": "pass"},
            {"check": "independent source parse equals every inventory record byte-for-byte", "result": "pass"},
            {"check": "every per-formula SHA-256 matches the exact UTF-8 TeX bytes", "result": "pass"},
            {"check": "all marker IDs are unique and all formula bodies are nonempty", "result": "pass"},
        ],
    }


def write_receipt(receipt: dict) -> None:
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    counts = receipt["counts"]
    inventory = receipt["formula_inventory"]
    syntax = counts["display_syntax"]
    report = f"""# Formula inventory audit

Status: **pass**

The independent source parse found {counts['formulas']} formulas: {counts['inline']} inline formulas and {counts['display']} displays. Every marker is tied to the formula that starts immediately after it, every formula body is nonempty, and every exact TeX hash matches.

Display count by syntax:

- bracket: {syntax['bracket']}
- equation: {syntax['equation']}
- equation*: {syntax['equation*']}
- align: {syntax['align']}
- align*: {syntax['align*']}
- gather*: {syntax['gather*']}

Inventory SHA-256: `{inventory['sha256']}`

Canonical record SHA-256: `{inventory['records_sha256']}`

Formula-sequence SHA-256: `{inventory['formula_sequence_sha256']}`

Source-file-set SHA-256: `{receipt['source_files']['set_sha256']}`
"""
    REPORT.write_text(report, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args()
    run_regressions()
    receipt = audit_current_inventory()
    if args.write_receipt:
        write_receipt(receipt)
    print(json.dumps({
        "status": receipt["status"],
        "counts": receipt["counts"],
        "inventory_sha256": receipt["formula_inventory"]["sha256"],
        "records_sha256": receipt["formula_inventory"]["records_sha256"],
        "formula_sequence_sha256": receipt["formula_inventory"]["formula_sequence_sha256"],
        "receipt_written": args.write_receipt,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
