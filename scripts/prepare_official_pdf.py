#!/usr/bin/env python3
"""Verify the frozen official PDF and create the audit's page inputs."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EXPECTED_SHA256 = "0e779481c4da40bd28d1e642e1d8ca57447d129610df28dfa5a11e9af8ae228f"
EXPECTED_BYTES = 2_959_204
EXPECTED_PAGES = 166
RENDER_DPI = 180
EXPECTED_RENDER_SIZE = (1530, 1980)


class PreparationError(RuntimeError):
    """Raised when an input or generated artifact fails a required check."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def command_path(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise PreparationError(
            f"Required Poppler command {name!r} was not found on PATH."
        )
    return path


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        rendered = " ".join(args)
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise PreparationError(
            f"Command failed with exit code {result.returncode}: {rendered}\n{detail}"
        )
    return result


def pdf_page_count(pdfinfo: str, pdf: Path) -> int:
    result = run_command([pdfinfo, str(pdf)])
    match = re.search(r"^Pages:\s+(\d+)\s*$", result.stdout, flags=re.MULTILINE)
    if match is None:
        raise PreparationError("pdfinfo did not report a page count.")
    return int(match.group(1))


def verify_pdf(pdf: Path, pdfinfo: str) -> None:
    if not pdf.is_file():
        raise PreparationError(f"Input PDF does not exist: {pdf}")
    observed_bytes = pdf.stat().st_size
    if observed_bytes != EXPECTED_BYTES:
        raise PreparationError(
            f"Input PDF has {observed_bytes} bytes; expected {EXPECTED_BYTES}."
        )
    observed_hash = sha256(pdf)
    if observed_hash != EXPECTED_SHA256:
        raise PreparationError(
            f"Input PDF SHA-256 is {observed_hash}; expected {EXPECTED_SHA256}."
        )
    observed_pages = pdf_page_count(pdfinfo, pdf)
    if observed_pages != EXPECTED_PAGES:
        raise PreparationError(
            f"pdfinfo reports {observed_pages} pages; expected {EXPECTED_PAGES}."
        )


def split_layout_text(layout_bytes: bytes) -> list[bytes]:
    chunks = layout_bytes.split(b"\x0c")
    if len(chunks) != EXPECTED_PAGES + 1:
        raise PreparationError(
            f"pdftotext produced {len(chunks) - 1} page separators; "
            f"expected {EXPECTED_PAGES}."
        )
    if chunks[-1].strip(b" \t\r\n"):
        raise PreparationError("Unexpected data follows the last pdftotext page separator.")
    pages = chunks[:-1]
    if any(not page.strip() for page in pages):
        empty = [index for index, page in enumerate(pages, start=1) if not page.strip()]
        raise PreparationError(f"pdftotext produced empty page text for pages {empty}.")
    for index, page in enumerate(pages, start=1):
        try:
            page.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PreparationError(
                f"pdftotext output for page {index} is not valid UTF-8: {exc}"
            ) from exc
    return pages


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise PreparationError(f"Generated render is not a PNG file: {path}")
    return struct.unpack(">II", header[16:24])


def collect_renders(directory: Path, prefix: str) -> dict[int, Path]:
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)\.png$")
    found: dict[int, Path] = {}
    for path in directory.iterdir():
        match = pattern.fullmatch(path.name)
        if match is None:
            continue
        page = int(match.group(1))
        if page in found:
            raise PreparationError(f"Duplicate render for PDF page {page}.")
        found[page] = path
    expected = set(range(1, EXPECTED_PAGES + 1))
    if set(found) != expected:
        missing = sorted(expected - set(found))
        extra = sorted(set(found) - expected)
        raise PreparationError(
            f"pdftoppm render set is incomplete: missing={missing}, extra={extra}."
        )
    for page, path in found.items():
        dimensions = png_size(path)
        if dimensions != EXPECTED_RENDER_SIZE:
            raise PreparationError(
                f"Render for page {page} is {dimensions[0]}x{dimensions[1]}; "
                f"expected {EXPECTED_RENDER_SIZE[0]}x{EXPECTED_RENDER_SIZE[1]}."
            )
    return found


def promote_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)


def prepare(input_pdf: Path, pdftotext: str, pdftoppm: str) -> None:
    paper_root = ROOT / "sources" / "official" / "paper"
    paper_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".source-preparation-", dir=ROOT) as temp_name:
        stage = Path(temp_name)
        staged_pdf = stage / "navier-stokes.pdf"
        shutil.copyfile(input_pdf, staged_pdf)

        layout = stage / "layout.txt"
        run_command(
            [
                pdftotext,
                "-layout",
                "-enc",
                "UTF-8",
                str(staged_pdf),
                str(layout),
            ]
        )
        page_texts = split_layout_text(layout.read_bytes())
        staged_pages = stage / "pages"
        staged_pages.mkdir()
        for page, content in enumerate(page_texts, start=1):
            (staged_pages / f"page-{page:03d}.txt").write_bytes(content)

        staged_renders = stage / "renders"
        staged_renders.mkdir()
        render_prefix = "render"
        run_command(
            [
                pdftoppm,
                "-f",
                "1",
                "-l",
                str(EXPECTED_PAGES),
                "-r",
                str(RENDER_DPI),
                "-png",
                str(staged_pdf),
                str(staged_renders / render_prefix),
            ]
        )
        render_files = collect_renders(staged_renders, render_prefix)

        promote_file(staged_pdf, paper_root / "navier-stokes.pdf")
        promote_file(layout, paper_root / "extracted" / "layout.txt")
        for page in range(1, EXPECTED_PAGES + 1):
            promote_file(
                staged_pages / f"page-{page:03d}.txt",
                paper_root / "extracted" / "pages" / f"page-{page:03d}.txt",
            )
            promote_file(
                render_files[page],
                paper_root / "renders" / "180dpi" / f"page-{page:03d}.png",
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the downloaded official Navier--Stokes PDF and create the "
            "text and 180-dpi page files used by the transcription audit."
        )
    )
    parser.add_argument("input_pdf", type=Path, help="downloaded official PDF")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="verify the input and Poppler tools without writing output files",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_pdf = args.input_pdf.expanduser().resolve()
    try:
        pdfinfo = command_path("pdfinfo")
        pdftotext = command_path("pdftotext")
        pdftoppm = command_path("pdftoppm")
        verify_pdf(input_pdf, pdfinfo)
        if args.check_only:
            run_command([pdftotext, "-v"])
            run_command([pdftoppm, "-v"])
            print("PASS: official PDF identity, page count, and Poppler commands are ready.")
            print(f"PDF SHA-256: {EXPECTED_SHA256}")
            print(f"PDF pages: {EXPECTED_PAGES}")
            return 0
        prepare(input_pdf, pdftotext, pdftoppm)
        print("PASS: official PDF inputs prepared for the transcription audit.")
        print(f"Page text files: {EXPECTED_PAGES}")
        print(f"180-dpi page renders: {EXPECTED_PAGES}")
        return 0
    except PreparationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
