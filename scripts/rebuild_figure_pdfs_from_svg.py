#!/usr/bin/env python3
"""Rebuild the six imported figure PDFs from the checked cropped SVGs.

The source SVGs keep the visible crop as vector outlines.  Converting those
SVGs with MuPDF removes the source PDF text layer that survives a page-box-only
crop.  The script also renders the old import, source crop, and replacement at
576 dpi and records image-difference measurements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import PIL
import pypdf
from pypdf import PdfReader


DPI = 576
PIXELS_PER_POINT = DPI // 72
MUTOOL_OPTIONS = (
    "compress,compress-fonts,compress-images,"
    "garbage=deduplicate,regenerate-id=no"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, check=True, capture_output=True)


def version(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True)
    value = (result.stdout + result.stderr).decode("utf-8", "replace").strip()
    return " ".join(value.split())


def require_tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"required tool not found: {name}")
    return str(Path(found).resolve())


def box_values(page: Any, attribute: str) -> list[float]:
    return [float(value) for value in getattr(page, attribute)]


def inspect_pdf(path: Path, pdftotext: str) -> dict[str, Any]:
    reader = PdfReader(path)
    if len(reader.pages) != 1:
        raise SystemExit(f"{path} has {len(reader.pages)} pages, expected 1")
    page = reader.pages[0]
    pypdf_text = page.extract_text() or ""
    poppler = run([pdftotext, "-enc", "UTF-8", str(path), "-"])
    poppler_text = poppler.stdout.decode("utf-8", "replace")
    resources = page.get("/Resources") or {}
    contents = page.get_contents()
    direct_keys = {
        key: key in page
        for key in ("/MediaBox", "/CropBox", "/TrimBox", "/BleedBox", "/ArtBox")
    }
    return {
        "bytes": path.stat().st_size,
        "sha256": digest(path),
        "page_count": 1,
        "effective_page_boxes_points": {
            "media": box_values(page, "mediabox"),
            "crop": box_values(page, "cropbox"),
            "trim": box_values(page, "trimbox"),
            "bleed": box_values(page, "bleedbox"),
            "art": box_values(page, "artbox"),
        },
        "direct_page_box_keys": direct_keys,
        "pypdf_extracted_character_count": len(pypdf_text.strip()),
        "pdftotext_extracted_character_count": len(poppler_text.strip()),
        "embedded_image_count": len(list(page.images)),
        "font_resource_count": len(resources.get("/Font") or {}),
        "xobject_resource_count": len(resources.get("/XObject") or {}),
        "decoded_content_stream_bytes": (
            len(contents.get_data()) if contents is not None else 0
        ),
    }


def check_replacement_pdf(record: dict[str, Any], width: int, height: int, path: Path) -> None:
    expected = [0.0, 0.0, float(width), float(height)]
    for name, values in record["effective_page_boxes_points"].items():
        if any(abs(a - b) > 1e-7 for a, b in zip(values, expected)):
            raise SystemExit(f"{path}: {name} box {values} differs from {expected}")
    if record["pypdf_extracted_character_count"] != 0:
        raise SystemExit(f"{path}: pypdf still extracts text")
    if record["pdftotext_extracted_character_count"] != 0:
        raise SystemExit(f"{path}: pdftotext still extracts text")
    if record["embedded_image_count"] != 0:
        raise SystemExit(f"{path}: replacement contains an embedded raster image")
    if record["font_resource_count"] != 0:
        raise SystemExit(f"{path}: replacement contains a font resource")
    if record["decoded_content_stream_bytes"] == 0:
        raise SystemExit(f"{path}: replacement has an empty content stream")


def render_pdf(pdftoppm: str, source: Path, prefix: Path) -> Path:
    output = prefix.with_suffix(".png")
    run(
        [
            pdftoppm,
            "-r",
            str(DPI),
            "-cropbox",
            "-singlefile",
            "-png",
            str(source),
            str(prefix),
        ]
    )
    if not output.is_file():
        raise SystemExit(f"render was not created: {output}")
    return output


def render_with_mutool(mutool: str, source: Path, output: Path) -> Path:
    run(
        [
            mutool,
            "draw",
            "-q",
            "-r",
            str(DPI),
            "-o",
            str(output),
            str(source),
        ]
    )
    if not output.is_file():
        raise SystemExit(f"MuPDF render was not created: {output}")
    return output


def render_source_crop(
    pdftoppm: str,
    source: Path,
    page: int,
    x: int,
    y: int,
    width: int,
    height: int,
    prefix: Path,
) -> Path:
    output = prefix.with_suffix(".png")
    run(
        [
            pdftoppm,
            "-f",
            str(page),
            "-l",
            str(page),
            "-r",
            str(DPI),
            "-x",
            str(x * PIXELS_PER_POINT),
            "-y",
            str(y * PIXELS_PER_POINT),
            "-W",
            str(width * PIXELS_PER_POINT),
            "-H",
            str(height * PIXELS_PER_POINT),
            "-singlefile",
            "-png",
            str(source),
            str(prefix),
        ]
    )
    if not output.is_file():
        raise SystemExit(f"source crop render was not created: {output}")
    return output


def image_record(root: Path, path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        width, height = image.size
        mode = image.mode
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        "pixel_width": width,
        "pixel_height": height,
        "mode": mode,
    }


def image_difference(first: Path, second: Path) -> tuple[dict[str, Any], np.ndarray]:
    with Image.open(first) as first_image, Image.open(second) as second_image:
        first_array = np.asarray(first_image.convert("RGB"), dtype=np.int16)
        second_array = np.asarray(second_image.convert("RGB"), dtype=np.int16)
    if first_array.shape != second_array.shape:
        raise SystemExit(
            f"render size mismatch: {first} {first_array.shape}, {second} {second_array.shape}"
        )
    absolute = np.abs(first_array - second_array)
    pixels_changed = int(np.count_nonzero(np.any(absolute != 0, axis=2)))
    total_pixels = int(first_array.shape[0] * first_array.shape[1])
    metrics = {
        "mean_absolute_error_per_channel": float(absolute.mean()),
        "root_mean_square_error_per_channel": float(
            math.sqrt(np.mean(np.square(absolute, dtype=np.float64)))
        ),
        "maximum_absolute_channel_difference": int(absolute.max()),
        "changed_channel_values": int(np.count_nonzero(absolute)),
        "changed_pixels": pixels_changed,
        "total_pixels": total_pixels,
        "changed_pixel_fraction": pixels_changed / total_pixels,
    }
    return metrics, absolute


def save_difference_image(absolute: np.ndarray, output: Path) -> None:
    strength = np.max(absolute, axis=2).astype(np.uint16)
    boosted = np.minimum(strength * 8, 255).astype(np.uint8)
    image = np.zeros((boosted.shape[0], boosted.shape[1], 3), dtype=np.uint8)
    image[:, :, 0] = boosted
    Image.fromarray(image, mode="RGB").save(output, optimize=True)


def make_comparison(
    source: Path,
    old: Path,
    replacement: Path,
    difference: Path,
    output: Path,
) -> None:
    inputs = [
        ("source crop", source),
        ("old page-box import", old),
        ("SVG-derived replacement", replacement),
        ("replacement/source difference x8", difference),
    ]
    panels: list[tuple[str, Image.Image]] = []
    for label, path in inputs:
        with Image.open(path) as opened:
            panel = opened.convert("RGB")
        panel.thumbnail((900, 700), Image.Resampling.LANCZOS)
        panels.append((label, panel))
    label_height = 34
    gap = 12
    width = sum(panel.width for _, panel in panels) + gap * (len(panels) - 1)
    height = max(panel.height for _, panel in panels) + label_height
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    cursor = 0
    for label, panel in panels:
        draw.text((cursor + 6, 8), label, fill="black", font=font)
        canvas.paste(panel, (cursor, label_height))
        cursor += panel.width + gap
    canvas.save(output, optimize=True)


def make_authority_comparison(
    svg_authority: Path,
    replacement: Path,
    difference: Path,
    output: Path,
) -> None:
    inputs = [
        ("cropped SVG authority, MuPDF render", svg_authority),
        ("replacement PDF, MuPDF render", replacement),
        ("replacement/SVG difference x8", difference),
    ]
    panels: list[tuple[str, Image.Image]] = []
    for label, path in inputs:
        with Image.open(path) as opened:
            panel = opened.convert("RGB")
        panel.thumbnail((1000, 750), Image.Resampling.LANCZOS)
        panels.append((label, panel))
    label_height = 34
    gap = 12
    width = sum(panel.width for _, panel in panels) + gap * (len(panels) - 1)
    height = max(panel.height for _, panel in panels) + label_height
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    cursor = 0
    for label, panel in panels:
        draw.text((cursor + 6, 8), label, fill="black", font=font)
        canvas.paste(panel, (cursor, label_height))
        cursor += panel.width + gap
    canvas.save(output, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()

    mutool = require_tool("mutool")
    pdftoppm = require_tool("pdftoppm")
    pdftotext = require_tool("pdftotext")

    spec_path = root / "evidence" / "figures" / "FIGURE_CROPS.json"
    original_receipt_path = root / "evidence" / "figures" / "FIGURE_CROP_RECEIPT.json"
    repair_receipt_path = (
        root / "evidence" / "figures" / "FIGURE_SVG_PDF_REPAIR_RECEIPT.json"
    )
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    original_receipt = json.loads(original_receipt_path.read_text(encoding="utf-8"))
    source_pdf = root / spec["source_pdf"]
    if digest(source_pdf) != spec["source_pdf_sha256"]:
        raise SystemExit("source PDF hash mismatch")

    previous: dict[str, Any] = {}
    if repair_receipt_path.is_file():
        prior = json.loads(repair_receipt_path.read_text(encoding="utf-8"))
        previous = {item["id"]: item for item in prior.get("figures", [])}

    original_by_id = {item["id"]: item for item in original_receipt["figures"]}
    qa_dir = root / "evidence" / "figures" / "replacement_qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    scratch = root / "tmp" / "pdfs" / "figure-repair"
    scratch.mkdir(parents=True, exist_ok=True)
    figure_dir = root / "reconstruction" / "assets" / "figures"

    figures: list[dict[str, Any]] = []
    for item in spec["figures"]:
        figure_id = item["id"]
        number = item["number"]
        svg = figure_dir / f"figure-{number}.svg"
        target = figure_dir / f"figure-{number}.pdf"
        old_render = qa_dir / f"figure-{number}-old-page-box-import-{DPI}dpi.png"
        source_render = qa_dir / f"figure-{number}-source-crop-{DPI}dpi.png"
        replacement_render = qa_dir / f"figure-{number}-replacement-{DPI}dpi.png"
        difference_render = qa_dir / f"figure-{number}-replacement-source-diff-x8.png"
        comparison = qa_dir / f"figure-{number}-comparison.png"
        svg_mutool_render = qa_dir / f"figure-{number}-svg-authority-{DPI}dpi-mutool.png"
        replacement_mutool_render = (
            qa_dir / f"figure-{number}-replacement-{DPI}dpi-mutool.png"
        )
        svg_difference_render = (
            qa_dir / f"figure-{number}-replacement-svg-diff-x8-mutool.png"
        )
        authority_comparison = qa_dir / f"figure-{number}-svg-authority-comparison.png"

        prior = previous.get(figure_id)
        if prior:
            legacy_pdf = prior["legacy_imported_pdf"]
            if not old_render.is_file():
                raise SystemExit(f"missing preserved old render: {old_render}")
        else:
            legacy_pdf = inspect_pdf(target, pdftotext)
            legacy_pdf["path"] = target.relative_to(root).as_posix()
            recorded = original_by_id[figure_id]
            if legacy_pdf["sha256"] != recorded["sha256"]:
                raise SystemExit(f"legacy PDF hash mismatch for {figure_id}")
            render_pdf(pdftoppm, target, old_render.with_suffix(""))

        first = scratch / f"figure-{number}-pass-a.pdf"
        second = scratch / f"figure-{number}-pass-b.pdf"
        command_a = [
            mutool,
            "convert",
            "-o",
            str(first),
            "-F",
            "pdf",
            "-O",
            MUTOOL_OPTIONS,
            str(svg),
        ]
        command_b = command_a.copy()
        command_b[3] = str(second)
        run(command_a)
        run(command_b)
        first_hash = digest(first)
        second_hash = digest(second)
        if first_hash != second_hash:
            raise SystemExit(f"non-deterministic MuPDF output for {figure_id}")
        os.replace(first, target)
        second.unlink()

        replacement_pdf = inspect_pdf(target, pdftotext)
        replacement_pdf["path"] = target.relative_to(root).as_posix()
        check_replacement_pdf(
            replacement_pdf,
            int(item["width"]),
            int(item["height"]),
            target,
        )
        if replacement_pdf["sha256"] != first_hash:
            raise SystemExit(f"replacement hash changed after installation for {figure_id}")

        render_source_crop(
            pdftoppm,
            source_pdf,
            int(item["pdf_page"]),
            int(item["x"]),
            int(item["y"]),
            int(item["width"]),
            int(item["height"]),
            source_render.with_suffix(""),
        )
        render_pdf(pdftoppm, target, replacement_render.with_suffix(""))
        render_with_mutool(mutool, svg, svg_mutool_render)
        render_with_mutool(mutool, target, replacement_mutool_render)

        old_source_metrics, _ = image_difference(old_render, source_render)
        replacement_source_metrics, absolute = image_difference(
            replacement_render, source_render
        )
        old_replacement_metrics, _ = image_difference(old_render, replacement_render)
        replacement_svg_metrics, svg_absolute = image_difference(
            replacement_mutool_render, svg_mutool_render
        )
        save_difference_image(absolute, difference_render)
        save_difference_image(svg_absolute, svg_difference_render)
        make_comparison(
            source_render,
            old_render,
            replacement_render,
            difference_render,
            comparison,
        )
        make_authority_comparison(
            svg_mutool_render,
            replacement_mutool_render,
            svg_difference_render,
            authority_comparison,
        )

        visual_inspection = {
            "status": "pending",
            "inspector_note": (
                "Inspect both comparison sheets and the full-resolution replacement render."
            ),
        }
        if (
            prior
            and prior.get("visual_inspection", {}).get("status") == "pass"
            and prior.get("svg_authority", {}).get("sha256") == digest(svg)
            and prior.get("replacement_pdf", {}).get("sha256")
            == replacement_pdf["sha256"]
            and prior.get("renders", {}).get("comparison", {}).get("sha256")
            == digest(comparison)
            and prior.get("renders", {})
            .get("svg_authority_comparison", {})
            .get("sha256")
            == digest(authority_comparison)
        ):
            visual_inspection = prior["visual_inspection"]

        lower_left = [
            float(item["x"]),
            float(792 - item["y"] - item["height"]),
            float(item["x"] + item["width"]),
            float(792 - item["y"]),
        ]
        figures.append(
            {
                "id": figure_id,
                "number": number,
                "source_locator": {
                    "pdf": spec["source_pdf"],
                    "pdf_sha256": spec["source_pdf_sha256"],
                    "page": item["pdf_page"],
                    "crop_top_left_points": [
                        item["x"],
                        item["y"],
                        item["width"],
                        item["height"],
                    ],
                    "crop_pdf_box_lower_left_points": lower_left,
                },
                "svg_authority": {
                    "path": svg.relative_to(root).as_posix(),
                    "sha256": digest(svg),
                    "bytes": svg.stat().st_size,
                    "root_width_points": item["width"],
                    "root_height_points": item["height"],
                    "root_view_box": [item["x"], item["y"], item["width"], item["height"]],
                    "text_elements": 0,
                    "visible_letters_and_symbols_are_vector_outlines": True,
                },
                "legacy_imported_pdf": legacy_pdf,
                "replacement_pdf": {
                    **replacement_pdf,
                    "determinism_check": {
                        "pass_a_sha256": first_hash,
                        "pass_b_sha256": second_hash,
                        "identical": True,
                    },
                },
                "renders": {
                    "old_page_box_import": image_record(root, old_render),
                    "source_crop": image_record(root, source_render),
                    "replacement": image_record(root, replacement_render),
                    "replacement_source_difference_x8": image_record(
                        root, difference_render
                    ),
                    "comparison": image_record(root, comparison),
                    "svg_authority_mutool": image_record(root, svg_mutool_render),
                    "replacement_mutool": image_record(root, replacement_mutool_render),
                    "replacement_svg_difference_x8_mutool": image_record(
                        root, svg_difference_render
                    ),
                    "svg_authority_comparison": image_record(root, authority_comparison),
                },
                "image_differences": {
                    "old_import_against_source_crop": old_source_metrics,
                    "replacement_against_source_crop": replacement_source_metrics,
                    "old_import_against_replacement": old_replacement_metrics,
                    "replacement_against_svg_authority_using_mutool": (
                        replacement_svg_metrics
                    ),
                },
                "visual_inspection": visual_inspection,
            }
        )

    receipt = {
        "schema": "navier-stokes-svg-pdf-repair-receipt/v1",
        "purpose": (
            "Replace page-box-only PDF imports with deterministic PDFs made from "
            "the checked cropped SVGs, preserving the visible vector crop while "
            "removing every extractable text character."
        ),
        "source_pdf_sha256": spec["source_pdf_sha256"],
        "conversion": {
            "command_template": (
                "mutool convert -o OUTPUT.pdf -F pdf -O "
                f"{MUTOOL_OPTIONS} INPUT.svg"
            ),
            "mutool_path": mutool,
            "mutool_version": version([mutool, "-v"]),
            "two_independent_conversions_required_to_match": True,
        },
        "render_and_text_tools": {
            "render_dpi": DPI,
            "pixels_per_pdf_point": PIXELS_PER_POINT,
            "pdf_render_command_template": (
                f"pdftoppm -r {DPI} -cropbox -singlefile -png "
                "INPUT.pdf OUTPUT_PREFIX"
            ),
            "source_crop_render_command_template": (
                f"pdftoppm -f PAGE -l PAGE -r {DPI} -x X_PIXELS -y Y_PIXELS "
                "-W WIDTH_PIXELS -H HEIGHT_PIXELS -singlefile -png "
                "SOURCE.pdf OUTPUT_PREFIX"
            ),
            "svg_and_pdf_mutool_render_command_template": (
                f"mutool draw -q -r {DPI} -o OUTPUT.png INPUT"
            ),
            "text_extraction_command_template": (
                "pdftotext -enc UTF-8 INPUT.pdf -"
            ),
            "pdftoppm_path": pdftoppm,
            "pdftoppm_version": version([pdftoppm, "-v"]),
            "pdftotext_path": pdftotext,
            "pdftotext_version": version([pdftotext, "-v"]),
            "python_version": platform.python_version(),
            "pypdf_version": pypdf.__version__,
            "pillow_version": PIL.__version__,
            "numpy_version": np.__version__,
        },
        "global_checks": {
            "figure_count": len(figures),
            "every_replacement_has_zero_pypdf_text": all(
                item["replacement_pdf"]["pypdf_extracted_character_count"] == 0
                for item in figures
            ),
            "every_replacement_has_zero_pdftotext_text": all(
                item["replacement_pdf"]["pdftotext_extracted_character_count"] == 0
                for item in figures
            ),
            "every_replacement_is_deterministic": all(
                item["replacement_pdf"]["determinism_check"]["identical"]
                for item in figures
            ),
            "every_replacement_is_vector_only_with_no_images_or_fonts": all(
                item["replacement_pdf"]["embedded_image_count"] == 0
                and item["replacement_pdf"]["font_resource_count"] == 0
                and item["replacement_pdf"]["decoded_content_stream_bytes"] > 0
                for item in figures
            ),
            "every_old_import_matches_the_source_crop_pixel_for_pixel": all(
                item["image_differences"]["old_import_against_source_crop"][
                    "changed_pixels"
                ]
                == 0
                for item in figures
            ),
            "every_replacement_matches_the_svg_authority_with_mutool_mae_below_0_05": all(
                item["image_differences"][
                    "replacement_against_svg_authority_using_mutool"
                ]["mean_absolute_error_per_channel"]
                < 0.05
                for item in figures
            ),
            "every_visual_inspection_passed": all(
                item["visual_inspection"]["status"] == "pass" for item in figures
            ),
            "page_box_interpretation": (
                "MuPDF writes an explicit MediaBox. Under PDF defaults the absent CropBox, "
                "TrimBox, BleedBox, and ArtBox take the same effective rectangle; both the "
                "direct keys and all five effective boxes are recorded for every figure."
            ),
        },
        "figures": figures,
        "limitations": [
            (
                "The raster comparison checks one Poppler rendering at 576 dpi; "
                "it is not an operator-by-operator equivalence proof for the two vector files."
            ),
            (
                "Visible labels are vector outlines in the replacement PDFs, so text "
                "extractors intentionally return no characters from the figure assets."
            ),
            (
                "The cropped SVG files retain full-page outline definitions and drawing "
                "commands outside the view box. The replacement PDF page clips that geometry; "
                "none of it remains extractable as text."
            ),
        ],
    }
    repair_receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
