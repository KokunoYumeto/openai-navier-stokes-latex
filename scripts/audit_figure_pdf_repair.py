#!/usr/bin/env python3
"""Audit the SVG-derived figure PDFs and their recorded QA evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from pypdf import PdfReader


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def effective_box(page: Any, name: str) -> list[float]:
    return [float(value) for value in getattr(page, name)]


def image_difference(first: Path, second: Path) -> dict[str, Any]:
    with Image.open(first) as first_image, Image.open(second) as second_image:
        first_array = np.asarray(first_image.convert("RGB"), dtype=np.int16)
        second_array = np.asarray(second_image.convert("RGB"), dtype=np.int16)
    if first_array.shape != second_array.shape:
        raise ValueError(f"image dimensions differ: {first} and {second}")
    absolute = np.abs(first_array - second_array)
    changed_pixels = int(np.count_nonzero(np.any(absolute != 0, axis=2)))
    total_pixels = int(first_array.shape[0] * first_array.shape[1])
    return {
        "mean_absolute_error_per_channel": float(absolute.mean()),
        "root_mean_square_error_per_channel": float(
            math.sqrt(np.mean(np.square(absolute, dtype=np.float64)))
        ),
        "maximum_absolute_channel_difference": int(absolute.max()),
        "changed_channel_values": int(np.count_nonzero(absolute)),
        "changed_pixels": changed_pixels,
        "total_pixels": total_pixels,
        "changed_pixel_fraction": changed_pixels / total_pixels,
    }


def compare_metrics(expected: dict[str, Any], actual: dict[str, Any], label: str) -> None:
    for key, expected_value in expected.items():
        actual_value = actual[key]
        if isinstance(expected_value, float):
            if not math.isclose(expected_value, actual_value, rel_tol=0.0, abs_tol=1e-15):
                raise ValueError(
                    f"{label}: metric {key} changed: {actual_value} != {expected_value}"
                )
        elif actual_value != expected_value:
            raise ValueError(
                f"{label}: metric {key} changed: {actual_value} != {expected_value}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()

    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise SystemExit("required tool not found: pdftotext")

    receipt_path = (
        root / "evidence" / "figures" / "FIGURE_SVG_PDF_REPAIR_RECEIPT.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt["schema"] != "navier-stokes-svg-pdf-repair-receipt/v1":
        raise SystemExit("unexpected receipt schema")
    if len(receipt["figures"]) != 6:
        raise SystemExit("receipt must contain six figures")
    legacy_receipt = json.loads(
        (root / "evidence" / "figures" / "FIGURE_CROP_RECEIPT.json").read_text(
            encoding="utf-8"
        )
    )
    if legacy_receipt.get("status") != "superseded_by_svg_pdf_repair":
        raise SystemExit("legacy page-box receipt is not marked superseded")
    ledger_records = [
        json.loads(line)
        for line in (
            root / "evidence" / "figures" / "FIGURE_LEDGER.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ledger_by_id = {record["id"]: record for record in ledger_records}

    failures: list[str] = []
    for item in receipt["figures"]:
        try:
            number = item["number"]
            svg = root / item["svg_authority"]["path"]
            pdf = root / item["replacement_pdf"]["path"]
            if digest(svg) != item["svg_authority"]["sha256"]:
                raise ValueError("SVG hash mismatch")
            if digest(pdf) != item["replacement_pdf"]["sha256"]:
                raise ValueError("replacement PDF hash mismatch")

            reader = PdfReader(pdf)
            if len(reader.pages) != 1:
                raise ValueError("replacement does not have exactly one page")
            page = reader.pages[0]
            expected_box = [
                0.0,
                0.0,
                float(item["svg_authority"]["root_width_points"]),
                float(item["svg_authority"]["root_height_points"]),
            ]
            for name in ("mediabox", "cropbox", "trimbox", "bleedbox", "artbox"):
                if effective_box(page, name) != expected_box:
                    raise ValueError(f"unexpected effective {name}")
            if (page.extract_text() or "").strip():
                raise ValueError("pypdf extracted text from replacement")
            result = subprocess.run(
                [pdftotext, "-enc", "UTF-8", str(pdf), "-"],
                check=True,
                capture_output=True,
            )
            if result.stdout.decode("utf-8", "replace").strip():
                raise ValueError("pdftotext extracted text from replacement")
            resources = page.get("/Resources") or {}
            if len(list(page.images)) != 0:
                raise ValueError("replacement contains an embedded raster image")
            if len(resources.get("/Font") or {}) != 0:
                raise ValueError("replacement contains a font resource")
            contents = page.get_contents()
            if contents is None or not contents.get_data():
                raise ValueError("replacement has an empty content stream")
            if not item["replacement_pdf"]["determinism_check"]["identical"]:
                raise ValueError("recorded conversions were not identical")
            ledger = ledger_by_id.get(f"{item['id']}-SVG-PDF-REPAIR")
            if not ledger:
                raise ValueError("repair ledger record is missing")
            if ledger["pdf_sha256"] != item["replacement_pdf"]["sha256"]:
                raise ValueError("repair ledger PDF hash mismatch")
            if ledger["svg_sha256"] != item["svg_authority"]["sha256"]:
                raise ValueError("repair ledger SVG hash mismatch")
            if ledger["visual_inspection"] != "pass":
                raise ValueError("repair ledger visual result is not pass")

            for render in item["renders"].values():
                path = root / render["path"]
                if digest(path) != render["sha256"]:
                    raise ValueError(f"render hash mismatch: {path}")
                with Image.open(path) as image:
                    if image.size != (render["pixel_width"], render["pixel_height"]):
                        raise ValueError(f"render dimensions changed: {path}")

            render_paths = {
                key: root / value["path"] for key, value in item["renders"].items()
            }
            pairs = {
                "old_import_against_source_crop": (
                    render_paths["old_page_box_import"],
                    render_paths["source_crop"],
                ),
                "replacement_against_source_crop": (
                    render_paths["replacement"],
                    render_paths["source_crop"],
                ),
                "old_import_against_replacement": (
                    render_paths["old_page_box_import"],
                    render_paths["replacement"],
                ),
                "replacement_against_svg_authority_using_mutool": (
                    render_paths["replacement_mutool"],
                    render_paths["svg_authority_mutool"],
                ),
            }
            for label, pair in pairs.items():
                compare_metrics(
                    item["image_differences"][label],
                    image_difference(*pair),
                    f"{item['id']} {label}",
                )
            if item["visual_inspection"]["status"] != "pass":
                raise ValueError("visual inspection is not marked pass")
        except Exception as error:
            failures.append(f"{item.get('id', number)}: {error}")

    checks = receipt["global_checks"]
    required_global = (
        "every_replacement_has_zero_pypdf_text",
        "every_replacement_has_zero_pdftotext_text",
        "every_replacement_is_deterministic",
        "every_replacement_is_vector_only_with_no_images_or_fonts",
        "every_old_import_matches_the_source_crop_pixel_for_pixel",
        "every_replacement_matches_the_svg_authority_with_mutool_mae_below_0_05",
        "every_visual_inspection_passed",
    )
    for name in required_global:
        if checks.get(name) is not True:
            failures.append(f"global check is not true: {name}")

    if failures:
        print("FAIL")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print("PASS: six SVG-derived figure PDFs, zero extracted text, page boxes, hashes, renders, metrics, and visual inspection")


if __name__ == "__main__":
    main()
