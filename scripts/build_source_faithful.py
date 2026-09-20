#!/usr/bin/env python3
"""Build the source-faithful PDF twice and accept only identical clean builds.

This command does not render pages or make any visual-review claim. It checks the
source snapshot, compiler exits, final compiler logs, PDF readability, page count,
and byte-for-byte agreement between two independent build directories.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = ROOT / "reconstruction"
ENTRYPOINT = SOURCE_ROOT / "main.tex"
STYLE = SOURCE_ROOT / "ns-edition.sty"
TMP_ROOT = ROOT / "tmp" / "pdfs" / "source-faithful-build"
OUTPUT_ROOT = ROOT / "output" / "pdf"

JOB_NAME = "source-faithful-reconstruction"
SOURCE_DATE_EPOCH = 1_789_862_400
LATEX_PASSES = 5
COMMAND_TIMEOUT_SECONDS = 600
EXPECTED_PAGES = 166
RUN_NAMES = ("pass-a", "pass-b")

ACCEPTED_PDF = OUTPUT_ROOT / f"{JOB_NAME}.pdf"
ACCEPTED_LOG = OUTPUT_ROOT / f"{JOB_NAME}.log"
RECEIPT = OUTPUT_ROOT / f"{JOB_NAME}.build-receipt.json"

EXPECTED_SECTIONS = (
    "sections/pp001-006.tex",
    "sections/pp007-012.tex",
    "sections/pp013-018.tex",
    "sections/pp019-024.tex",
    "sections/pp025-030.tex",
    "sections/pp031-036.tex",
    "sections/pp037-042.tex",
    "sections/pp043-048.tex",
    "sections/pp049-054.tex",
    "sections/pp055-060.tex",
    "sections/pp061-066.tex",
    "sections/pp067-072.tex",
    "sections/pp073-078.tex",
    "sections/pp079-084.tex",
    "sections/pp085-090.tex",
    "sections/pp091-096.tex",
    "sections/pp097-102.tex",
    "sections/pp103-108.tex",
    "sections/pp109-114.tex",
    "sections/pp115-120.tex",
    "sections/pp121-126.tex",
    "sections/pp127-132.tex",
    "sections/pp133-138.tex",
    "sections/pp139-144.tex",
    "sections/pp145-150.tex",
    "sections/pp151-156.tex",
    "sections/pp157-162.tex",
    "sections/pp163-164.tex",
    "sections/pp165-166.tex",
)

LOG_CATEGORIES = (
    "fatal",
    "undefined",
    "duplicate",
    "overfull",
    "missing_glyph",
    "rerun_required",
)

LOG_PATTERNS = (
    ("fatal", "tex-error-line", re.compile(r"^!", re.IGNORECASE)),
    ("fatal", "latex-error", re.compile(r"(?:LaTeX|Package\s+\S+)\s+Error:", re.IGNORECASE)),
    ("fatal", "emergency-stop", re.compile(r"Emergency stop", re.IGNORECASE)),
    ("fatal", "fatal-error", re.compile(r"Fatal error occurred", re.IGNORECASE)),
    ("fatal", "no-output", re.compile(r"No pages of output", re.IGNORECASE)),
    ("fatal", "undefined-control-sequence", re.compile(r"Undefined control sequence", re.IGNORECASE)),
    (
        "undefined",
        "undefined-reference-or-citation",
        re.compile(r"(?:Reference|Citation).+undefined", re.IGNORECASE),
    ),
    (
        "undefined",
        "undefined-summary",
        re.compile(r"There were undefined (?:references|citations)", re.IGNORECASE),
    ),
    (
        "undefined",
        "missing-destination",
        re.compile(r"has been referenced but does not exist", re.IGNORECASE),
    ),
    ("duplicate", "multiply-defined", re.compile(r"multiply[- ]defined", re.IGNORECASE)),
    (
        "duplicate",
        "duplicate-destination",
        re.compile(r"(?:destination with the same identifier|duplicate destination)", re.IGNORECASE),
    ),
    ("overfull", "overfull-box", re.compile(r"Overfull \\[hv]box", re.IGNORECASE)),
    ("missing_glyph", "missing-character", re.compile(r"Missing character:", re.IGNORECASE)),
    (
        "rerun_required",
        "labels-changed",
        re.compile(
            r"(?:Label\(s\) may have changed|Rerun to get (?:cross-references|outlines) right|Please rerun LaTeX)",
            re.IGNORECASE,
        ),
    ),
)


class BuildError(RuntimeError):
    """A release-blocking build or validation error."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise BuildError(f"Expected a project path, got {path.name!r}") from exc


def file_record(path: Path, *, base: Path = ROOT) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(base.resolve()).as_posix()
    except ValueError as exc:
        raise BuildError(f"Cannot record a file outside the expected root: {path.name!r}") from exc
    if not resolved.is_file():
        raise BuildError(f"Expected file is missing: {relative}")
    return {
        "path": relative,
        "bytes": resolved.stat().st_size,
        "sha256": sha256_path(resolved),
    }


def ensure_child(parent: Path, child: Path) -> None:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError as exc:
        raise BuildError(f"Refusing a path outside {project_path(parent)}") from exc


def sanitize(text: str, *, build_root: Path | None = None) -> str:
    replacements: list[tuple[str, str]] = []
    if build_root is not None:
        replacements.append((str(build_root.resolve()), "${BUILD_TMP}"))
        replacements.append((build_root.resolve().as_posix(), "${BUILD_TMP}"))
    replacements.extend(
        (
            (str(ROOT.resolve()), "${PROJECT_ROOT}"),
            (ROOT.resolve().as_posix(), "${PROJECT_ROOT}"),
            (str(Path.home().resolve()), "${USER_HOME}"),
            (Path.home().resolve().as_posix(), "${USER_HOME}"),
        )
    )
    result = text
    for source, target in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        result = result.replace(source, target)
    result = re.sub(r"(?i)[A-Z]:[/\\]Users[/\\][^/\\\r\n]+", "${USER_HOME}", result)
    return result.replace("\r\n", "\n").replace("\r", "\n")


def stable_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "SOURCE_DATE_EPOCH": str(SOURCE_DATE_EPOCH),
            "FORCE_SOURCE_DATE": "1",
            "TZ": "UTC",
            "PYTHONHASHSEED": "0",
            "max_print_line": "10000",
        }
    )
    return environment


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)


def run_command(
    arguments: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if not cwd.is_dir():
        raise BuildError(f"Command working directory is missing: {cwd.name}")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        list(arguments),
        cwd=str(cwd),
        env=dict(environment or stable_environment()),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate_process_tree(process)
        output, _ = process.communicate()
    return {
        "arguments": list(arguments),
        "cwd": str(cwd.resolve()),
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "output": output,
    }


def require_tool(name: str) -> Path:
    located = shutil.which(name)
    if located is None:
        raise BuildError(f"Required command is missing: {name}")
    path = Path(located).resolve()
    if not path.is_file():
        raise BuildError(f"Required command did not resolve to a file: {name}")
    return path


def tool_record(name: str, path: Path, arguments: Sequence[str]) -> dict[str, Any]:
    result = run_command(
        [str(path), *arguments],
        cwd=ROOT,
        timeout=30,
        environment=stable_environment(),
    )
    if result["timed_out"] or result["exit_code"] != 0:
        raise BuildError(f"Could not read the {name} version")
    version_lines = [line.strip() for line in result["output"].splitlines() if line.strip()]
    if not version_lines:
        raise BuildError(f"The {name} version command returned no text")
    return {
        "command": name,
        "resolved_path": sanitize(str(path)),
        "executable_sha256": sha256_path(path),
        "version": sanitize(" | ".join(version_lines[:3])),
    }


def source_file_paths() -> list[Path]:
    if not ENTRYPOINT.is_file() or not STYLE.is_file():
        raise BuildError("The source-faithful entrypoint or style file is missing")
    main_text = ENTRYPOINT.read_text(encoding="utf-8-sig")
    inputs = re.findall(r"\\input\{([^{}]+)\}", main_text)
    normalized_inputs = [item if item.endswith(".tex") else item + ".tex" for item in inputs]
    if tuple(normalized_inputs) != EXPECTED_SECTIONS:
        raise BuildError(
            "The main file does not contain the exact ordered section list for source pages 001-166"
        )
    style_text = STYLE.read_text(encoding="utf-8-sig")
    figures = re.findall(r"\\NSDeclareFigure\{[^{}]+\}\{([^{}]+)\}", style_text)
    if len(figures) != 6 or len(set(figures)) != 6:
        raise BuildError("The style file must declare exactly six distinct checked figures")
    relative_paths = ["main.tex", "ns-edition.sty", *normalized_inputs, *figures]
    if len(relative_paths) != len(set(relative_paths)):
        raise BuildError("The source input list contains a duplicate path")
    paths: list[Path] = []
    for relative in relative_paths:
        candidate = (SOURCE_ROOT / relative).resolve()
        try:
            candidate.relative_to(SOURCE_ROOT.resolve())
        except ValueError as exc:
            raise BuildError(f"A source input escapes the reconstruction directory: {relative}") from exc
        if candidate.is_symlink():
            raise BuildError(f"Symlinked source inputs are not accepted: {relative}")
        if not candidate.is_file():
            raise BuildError(f"A declared source input is missing: {relative}")
        paths.append(candidate)
    return paths


def records_for_paths(paths: Iterable[Path], *, base: Path) -> list[dict[str, Any]]:
    return sorted(
        (file_record(path, base=base) for path in paths),
        key=lambda record: record["path"],
    )


def copy_source_snapshot(paths: Iterable[Path], destination: Path) -> list[dict[str, Any]]:
    if destination.exists():
        raise BuildError("The source snapshot directory was not clean")
    destination.mkdir(parents=True)
    copied: list[Path] = []
    for source in paths:
        relative = source.resolve().relative_to(SOURCE_ROOT.resolve())
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target)
    return records_for_paths(copied, base=destination)


def scan_release_blockers(text: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for category, code, pattern in LOG_PATTERNS:
            if pattern.search(line):
                findings.append(
                    {
                        "category": category,
                        "code": code,
                        "line": line_number,
                        "text": sanitize(line.strip()),
                    }
                )
    counts = {
        category: sum(item["category"] == category for item in findings)
        for category in LOG_CATEGORIES
    }
    return {
        "status": "pass" if not findings else "fail",
        "counts": counts,
        "findings": findings,
    }


def command_record(result: Mapping[str, Any], *, build_root: Path) -> dict[str, Any]:
    return {
        "arguments": [sanitize(str(item), build_root=build_root) for item in result["arguments"]],
        "cwd": sanitize(str(result["cwd"]), build_root=build_root),
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
    }


def pdfinfo_record(pdfinfo: Path, pdf: Path, *, build_root: Path) -> tuple[dict[str, Any], str]:
    result = run_command(
        [str(pdfinfo), str(pdf.resolve())],
        cwd=pdf.parent,
        timeout=60,
        environment=stable_environment(),
    )
    if result["timed_out"] or result["exit_code"] != 0:
        raise BuildError("pdfinfo could not read a completed build PDF")
    match = re.search(r"^Pages:\s+(\d+)\s*$", result["output"], flags=re.MULTILINE)
    if match is None:
        raise BuildError("pdfinfo did not report a page count")
    pages = int(match.group(1))
    if pages != EXPECTED_PAGES:
        raise BuildError(f"Expected {EXPECTED_PAGES} PDF pages, found {pages}")
    sanitized_output = sanitize(result["output"], build_root=build_root)
    return (
        {
            "command": command_record(result, build_root=build_root),
            "pages": pages,
            "output_sha256": sha256_bytes(sanitized_output.encode("utf-8")),
        },
        sanitized_output,
    )


def build_one_run(
    run_name: str,
    *,
    snapshot: Path,
    build_root: Path,
    pdflatex: Path,
    pdfinfo: Path,
    miktex: bool,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    run_root = build_root / run_name
    source_dir = run_root / "reconstruction"
    output_dir = run_root / "out"
    if run_root.exists():
        raise BuildError(f"The {run_name} directory was not clean")
    shutil.copytree(snapshot, source_dir)
    output_dir.mkdir(parents=True)

    command = [
        str(pdflatex),
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "-no-shell-escape",
        "-recorder",
        f"-jobname={JOB_NAME}",
        f"-output-directory={output_dir.resolve()}",
        str((source_dir / "main.tex").resolve()),
    ]
    if miktex:
        command.insert(1, "--disable-installer")

    pass_records: list[dict[str, Any]] = []
    console_parts: list[str] = []
    final_console_raw = ""
    for pass_number in range(1, LATEX_PASSES + 1):
        result = run_command(
            command,
            cwd=source_dir,
            timeout=COMMAND_TIMEOUT_SECONDS,
            environment=stable_environment(),
        )
        final_console_raw = result["output"]
        console_parts.append(
            f"===== compiler pass {pass_number} of {LATEX_PASSES} =====\n"
            + sanitize(result["output"], build_root=build_root)
        )
        pass_records.append(
            {
                "number": pass_number,
                **command_record(result, build_root=build_root),
            }
        )
        if result["timed_out"]:
            raise BuildError(f"{run_name}, compiler pass {pass_number}, timed out")
        if result["exit_code"] != 0:
            raise BuildError(f"{run_name}, compiler pass {pass_number}, exited with an error")

    pdf = output_dir / f"{JOB_NAME}.pdf"
    tex_log = output_dir / f"{JOB_NAME}.log"
    if not pdf.is_file() or not tex_log.is_file():
        raise BuildError(f"{run_name} did not produce both the expected PDF and TeX log")
    pdf_payload = pdf.read_bytes()
    if not pdf_payload.startswith(b"%PDF-") or b"%%EOF" not in pdf_payload[-2048:]:
        raise BuildError(f"{run_name} produced a file that does not have a complete PDF envelope")
    immediate_pdf_hash = sha256_bytes(pdf_payload)

    raw_tex_log = tex_log.read_text(encoding="utf-8", errors="replace")
    tex_log_checks = scan_release_blockers(raw_tex_log)
    final_console_checks = scan_release_blockers(final_console_raw)
    if tex_log_checks["status"] != "pass" or final_console_checks["status"] != "pass":
        raise BuildError(f"{run_name} contains release-blocking compiler findings")

    pdfinfo_data, pdfinfo_text = pdfinfo_record(pdfinfo, pdf, build_root=build_root)
    console_text = "\n".join(console_parts).rstrip() + "\n"
    sanitized_tex_log = sanitize(raw_tex_log, build_root=build_root).rstrip() + "\n"
    retained_names = {
        "pdf": f"{JOB_NAME}.{run_name}.pdf",
        "console": f"{JOB_NAME}.{run_name}.console.txt",
        "tex_log": f"{JOB_NAME}.{run_name}.log",
        "pdfinfo": f"{JOB_NAME}.{run_name}.pdfinfo.txt",
    }
    payloads = {
        retained_names["pdf"]: pdf_payload,
        retained_names["console"]: console_text.encode("utf-8"),
        retained_names["tex_log"]: sanitized_tex_log.encode("utf-8"),
        retained_names["pdfinfo"]: pdfinfo_text.encode("utf-8"),
    }
    record = {
        "name": run_name,
        "clean_directory": True,
        "compiler_passes": pass_records,
        "immediate_pdf": {
            "bytes": len(pdf_payload),
            "sha256": immediate_pdf_hash,
        },
        "immediate_tex_log_sha256": sha256_path(tex_log),
        "release_checks": {
            "final_tex_log": tex_log_checks,
            "final_compiler_console": final_console_checks,
            "note": "The compiler transcript retains all passes; release checks use the final TeX log and the final compiler pass.",
        },
        "pdfinfo": pdfinfo_data,
        "retained_names": retained_names,
    }
    return record, payloads


def atomic_write(path: Path, payload: bytes) -> None:
    ensure_child(OUTPUT_ROOT, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".next", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if sha256_path(temporary) != sha256_bytes(payload):
            raise BuildError(f"A staged output copy failed verification: {path.name}")
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def publish_payloads(payloads: Mapping[str, bytes]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for name, payload in payloads.items():
        destination = OUTPUT_ROOT / name
        atomic_write(destination, payload)
        record = file_record(destination)
        if record["sha256"] != sha256_bytes(payload) or record["bytes"] != len(payload):
            raise BuildError(f"An output copy changed after acceptance: {name}")
        records[name] = record
    return records


def iso_utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def dry_run_plan() -> dict[str, Any]:
    paths = source_file_paths()
    ensure_child(ROOT, SOURCE_ROOT)
    ensure_child(ROOT, TMP_ROOT)
    ensure_child(ROOT, OUTPUT_ROOT)
    return {
        "schema": "navier-stokes-source-faithful-build-plan/v1",
        "status": "dry_run",
        "commands_executed": False,
        "files_written": False,
        "entrypoint": project_path(ENTRYPOINT),
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "independent_clean_builds": len(RUN_NAMES),
        "compiler_passes_per_build": LATEX_PASSES,
        "expected_pages": EXPECTED_PAGES,
        "source_inputs": records_for_paths(paths, base=ROOT),
        "required_tools": {
            "pdflatex": sanitize(shutil.which("pdflatex") or "not found"),
            "pdfinfo": sanitize(shutil.which("pdfinfo") or "not found"),
        },
        "outputs": [
            project_path(ACCEPTED_PDF),
            project_path(ACCEPTED_LOG),
            project_path(RECEIPT),
            *[
                project_path(OUTPUT_ROOT / f"{JOB_NAME}.{run_name}.{suffix}")
                for run_name in RUN_NAMES
                for suffix in ("pdf", "console.txt", "log", "pdfinfo.txt")
            ],
        ],
        "visual_review_performed": False,
    }


def build() -> dict[str, Any]:
    paths = source_file_paths()
    source_before = records_for_paths(paths, base=SOURCE_ROOT)
    pdflatex = require_tool("pdflatex")
    pdfinfo = require_tool("pdfinfo")
    tools = {
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "pdflatex": tool_record("pdflatex", pdflatex, ("--version",)),
        "pdfinfo": tool_record("pdfinfo", pdfinfo, ("-v",)),
    }
    miktex = "miktex" in tools["pdflatex"]["version"].lower()

    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    work_root = Path(tempfile.mkdtemp(prefix="run-", dir=TMP_ROOT)).resolve()
    ensure_child(TMP_ROOT, work_root)
    run_records: list[dict[str, Any]] = []
    retained_payloads: dict[str, bytes] = {}
    try:
        snapshot = work_root / "snapshot" / "reconstruction"
        snapshot_records = copy_source_snapshot(paths, snapshot)
        if snapshot_records != source_before:
            raise BuildError("The clean source snapshot does not match the recorded source inputs")
        for run_name in RUN_NAMES:
            record, payloads = build_one_run(
                run_name,
                snapshot=snapshot,
                build_root=work_root,
                pdflatex=pdflatex,
                pdfinfo=pdfinfo,
                miktex=miktex,
            )
            run_records.append(record)
            retained_payloads.update(payloads)
        hashes = [record["immediate_pdf"]["sha256"] for record in run_records]
        if len(set(hashes)) != 1:
            raise BuildError(f"The two clean PDF builds are not byte-identical: {hashes}")
        source_after = records_for_paths(source_file_paths(), base=SOURCE_ROOT)
        if source_after != source_before:
            raise BuildError("The reconstruction sources changed while the build was running")

        accepted_pdf_payload = retained_payloads[f"{JOB_NAME}.pass-b.pdf"]
        accepted_log_payload = retained_payloads[f"{JOB_NAME}.pass-b.log"]
        retained_payloads[ACCEPTED_PDF.name] = accepted_pdf_payload
        retained_payloads[ACCEPTED_LOG.name] = accepted_log_payload
    finally:
        shutil.rmtree(work_root)

    published = publish_payloads(retained_payloads)
    for record in run_records:
        names = record.pop("retained_names")
        record["retained"] = {kind: published[name] for kind, name in names.items()}
        if record["retained"]["pdf"]["sha256"] != record["immediate_pdf"]["sha256"]:
            raise BuildError(f"The retained PDF hash changed for {record['name']}")

    accepted_pdf = published[ACCEPTED_PDF.name]
    accepted_log = published[ACCEPTED_LOG.name]
    if accepted_pdf["sha256"] != run_records[-1]["immediate_pdf"]["sha256"]:
        raise BuildError("The accepted PDF hash does not match the second clean build")

    receipt = {
        "schema": "navier-stokes-source-faithful-pdf-build/v1",
        "status": "pass",
        "completed_at_utc": iso_utc_now(),
        "builder": file_record(Path(__file__)),
        "entrypoint": file_record(ENTRYPOINT),
        "style": file_record(STYLE),
        "source_inputs": records_for_paths(paths, base=ROOT),
        "source_unchanged_during_build": True,
        "environment": {
            "SOURCE_DATE_EPOCH": str(SOURCE_DATE_EPOCH),
            "FORCE_SOURCE_DATE": "1",
            "TZ": "UTC",
            "PYTHONHASHSEED": "0",
            "max_print_line": "10000",
        },
        "tools": tools,
        "runs": run_records,
        "deterministic_rebuilds": len(RUN_NAMES),
        "byte_identical": True,
        "immediate_pdf_hashes": [record["immediate_pdf"]["sha256"] for record in run_records],
        "accepted_pdf": accepted_pdf,
        "accepted_log": accepted_log,
        "accepted_from_run": RUN_NAMES[-1],
        "expected_pages": EXPECTED_PAGES,
        "temporary_build_directories_removed_before_acceptance": True,
        "publication_performed": False,
        "visual_qa": {
            "performed": False,
            "claimed": False,
            "note": "This receipt does not accept page appearance. Rendered-page review must be recorded separately for this exact PDF hash.",
        },
    }
    receipt_payload = (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    atomic_write(RECEIPT, receipt_payload)
    return {
        "status": "pass",
        "accepted_pdf": accepted_pdf,
        "receipt": file_record(RECEIPT),
        "byte_identical": True,
        "visual_review_performed": False,
    }


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and hash the expected inputs, then print the build plan without running tools or writing files.",
    )
    return command


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    arguments = parser().parse_args(argv)
    try:
        result = dry_run_plan() if arguments.dry_run else build()
    except Exception as exc:
        failure = {
            "schema": "navier-stokes-source-faithful-build-failure/v1",
            "status": "fail",
            "error_type": type(exc).__name__,
            "message": sanitize(str(exc)),
            "accepted": False,
            "visual_review_performed": False,
        }
        print(json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
