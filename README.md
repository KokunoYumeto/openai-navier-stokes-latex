# Finite Time Blowup for Navier--Stokes: Independent LaTeX Reconstruction

This repository contains an independently prepared, editable LaTeX reconstruction of OpenAI's 166-page paper *Finite Time Blowup for Navier--Stokes*. It is page-corresponded to the official PDF and preserves the source's wording, mathematical notation, numbering, cross-references, figures, appendices, and bibliography.

This is not an official OpenAI source release. It is a source-faithful reconstruction made because a bounded search of the public official surfaces listed below did not find complete manuscript source. That result is limited to the places and time searched; it is not proof that source does not exist privately, under another name, or at a later date.

## Official sources and frozen identities

| Role | Official location | Frozen identity used for this reconstruction |
| --- | --- | --- |
| Paper; transcription authority | [OpenAI PDF](https://cdn.openai.com/pdf/32d9f210-8b73-45e0-91bc-82a30aef8a9a/navier-stokes.pdf) | 2,959,204 bytes; 166 pages; SHA-256 `0e779481c4da40bd28d1e642e1d8ca57447d129610df28dfa5a11e9af8ae228f` |
| Release description and status language | [OpenAI announcement](https://openai.com/index/navier-stokes-solution/) | Frozen HTML SHA-256 `c2f55d8b2cc538bc9cd93503937440303cfc9afbef78895240db54ca3de62179` |
| Official Lean source and metadata | [OpenAI Lean repository at commit `f9e8bc5...`](https://github.com/openai/NavierStokesAndEuler/commit/f9e8bc5b38b6e212696e8a30e3e91517af887bbd) | Commit `f9e8bc5b38b6e212696e8a30e3e91517af887bbd`; [Git tree `a503f076...`](https://api.github.com/repos/openai/NavierStokesAndEuler/git/trees/a503f07635f200c0f2f9c5361df1fa07f95c4741); audit-time local archive SHA-256 `a9322b2112ef89c9a0cbb5029578cd672a757fe715a565d55f032e0b443cb7a7` (archive not bundled) |
| Official problem formulation | [Clay Mathematics Institute statement](https://www.claymath.org/wp-content/uploads/2022/06/navierstokes.pdf) | 203,736 bytes; 6 PDF pages; SHA-256 `c1b5f27b1a64705cfaf1afceea513db5deedca8a18ca56ab32e7f86445a06d0c` |

The PDF displays `OPENAI` as its author and no visible version label. No semantic version has been invented here. The Lean repository is the official source for its own files and metadata, not the transcription authority for the paper's prose or typesetting. This repository did not run or independently certify the Lean code.

## Verification status

The release gate for this repository accepts only a byte state for which [`TRANSCRIPTION_AUDIT.json`](evidence/transcription/TRANSCRIPTION_AUDIT.json) has status `pass` and its recorded hashes match every staged section file. The accepted audit state has:

- 166 source-page markers and 166 page-check records, covering pages 1 through 166 with no pending range;
- 6,175 individually identified mathematical occurrences: 5,408 inline and 767 displayed;
- page-level `visual_inspection`, `text_order`, and `formula_visual_check` results of `pass`;
- 527 labels, 1,671 references, and no unresolved internal reference recorded by the structural audit;
- all 22 bibliography entries; and
- six checked source figures, with no redrawing.

Each page was compared with a 180-dpi rendering of the frozen official PDF. Text extraction was used only as a draft aid. It was never treated as verification. Formula checks used the visible page as authority for symbols, delimiters, indices, exponents, signs, constants, domains, quantifiers, asymptotics, printed numbers, and cross-references. [`PDF_TEX_CORRESPONDENCE.json`](evidence/transcription/PDF_TEX_CORRESPONDENCE.json) binds each source page to exact LaTeX spans and hashes; [`FORMULA_INVENTORY.json`](evidence/transcription/FORMULA_INVENTORY.json) gives the formula locators and source text.

The supplied cumulative PDF has 166 pages. Its exact byte hash, and the hashes of every other staged file, are recorded in [`MANIFEST.sha256`](MANIFEST.sha256). The audit establishes the reported transcription checks; it does not turn this repository into official source, independently prove the paper's mathematics, or decide any Clay Mathematics Institute recognition or prize process.

The corrected deterministic PDF is 4,579,755 bytes with SHA-256 `1e8e3f23a2fa67c5a1daf39202cf0004552966668defc36784ef1e73be3483d3`. Two isolated clean builds ran five pdfTeX passes each and produced exactly the same PDF bytes. All 166 output pages were compared with the matching official pages through the exact-byte build record `NS-BUILD-20260920-006` and visual-review record `NS-VQA-20260920-005`; the corrected PDF bytes named above passed that review.

The notation checks are under [`evidence/integration/`](evidence/integration/). The static manuscript-to-Lean map under [`evidence/lean/`](evidence/lean/) lists all 80 numbered statements and records 132 declaration-source locators at the frozen official commit. The classifications are bounded source-reading judgments, not proof that those files compile or that each manuscript statement has been formally verified. Lean, Lake, and Elan were not run for that check.

## Build

The recorded full build used MiKTeX pdfTeX 1.40.29. A current TeX Live or MiKTeX installation needs the packages named in `reconstruction/ns-edition.sty`, including the AMS packages, `mathtools`, `mathpazo`, `mathrsfs`, `graphicx`, `microtype`, `enumitem`, `geometry`, `fancyhdr`, `hyperref`, and `cleveref`.

For an ordinary local build, run:

```powershell
Set-Location reconstruction
pdflatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex
pdflatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex
```

The result is `reconstruction/main.pdf`. Two passes resolve the table of contents and internal references. The edition suppresses volatile PDF dates and trailer identifiers, but exact PDF bytes can still depend on the TeX engine, package versions, and installed fonts; preserve those inputs when bit-for-bit reproduction matters.

For the checked release build, run this from the repository root:

```powershell
python scripts/build_source_faithful.py
```

That builder uses two isolated clean directories, runs five pdfTeX passes in each one, checks the final logs and page counts, requires the two PDFs to be byte-for-byte identical, and retains both PDFs, logs, console records, and `pdfinfo` records. Its machine-readable receipt is [`source-faithful-reconstruction.build-receipt.json`](output/pdf/source-faithful-reconstruction.build-receipt.json).

The receipts also name temporary page renders, contact sheets, build logs, and console transcripts from the checked build workspace. Those temporary files are not part of this repository; their paths and hashes are kept in the receipts so the reported checks remain specific about the artifacts that were inspected.

## Prepare the official PDF inputs

The official PDF, extracted page text, and 180-dpi page renders are deliberately not bundled. Download the PDF from the official link above and save it as `navier-stokes.pdf` in the repository root. Poppler's `pdfinfo`, `pdftotext`, and `pdftoppm` commands must be on `PATH`.

From the repository root, the complete preparation command is:

```powershell
python scripts/prepare_official_pdf.py navier-stokes.pdf
```

Before writing anything, the script requires the exact 2,959,204-byte PDF, SHA-256 `0e779481c4da40bd28d1e642e1d8ca57447d129610df28dfa5a11e9af8ae228f`, and a `pdfinfo` page count of 166. It then writes the frozen PDF to `sources/official/paper/navier-stokes.pdf`, creates all 166 UTF-8 page-text files under `sources/official/paper/extracted/pages/`, and creates all 166 PNG page renders at 180 dpi under `sources/official/paper/renders/180dpi/`. The text remains a drafting aid; the page images and official PDF remain the visual authority. Append `--check-only` to perform the identity, page-count, and tool checks without writing files.

The structural audit under `scripts/audit_transcription.py` expects exactly those generated paths.

## Figures

The paper's six figures occur on official PDF pages 4, 5, 9, 10, 13, and 15. The checked cropped SVGs keep the visible artwork as vector outlines. The current PDF assets were made deterministically from those SVGs so that no hidden text from the surrounding source pages remains inside the figure files. Both `pypdf` and `pdftotext` extract zero characters from every current figure PDF, and two independent conversions produced the same bytes for each figure.

[`FIGURE_SVG_PDF_REPAIR_RECEIPT.json`](evidence/figures/FIGURE_SVG_PDF_REPAIR_RECEIPT.json) records the current PDF and SVG hashes, page boxes, source-page crops, high-resolution comparisons, difference measurements, and visual checks. [`FIGURE_LEDGER.jsonl`](evidence/figures/FIGURE_LEDGER.jsonl) links each current PDF to the earlier page-box import that it replaced. [`FIGURE_CROP_RECEIPT.json`](evidence/figures/FIGURE_CROP_RECEIPT.json) is kept only as clearly marked history for those replaced imports.

From the repository root, the current figure evidence can be checked with:

```powershell
python scripts/audit_figure_pdf_repair.py .
```

After preparing the official PDF inputs, the six PDFs and their evidence can be rebuilt with `python scripts/rebuild_figure_pdfs_from_svg.py .`.

## Repository contents

- `reconstruction/main.tex` is the master document.
- `reconstruction/sections/` contains the complete page-corresponded source in bounded ranges.
- `reconstruction/assets/figures/` contains the six checked vector figure assets.
- `output/pdf/source-faithful-reconstruction.pdf` is the cumulative 166-page build.
- `evidence/source/` records source custody and the bounded official-source search.
- `evidence/transcription/` contains the fail-closed audit, page correspondence, formula inventory, page-check ledgers, and uncertainty ledgers.
- `evidence/figures/` records figure provenance and inspection.
- `evidence/integration/` records the full notation audit.
- `evidence/lean/` contains the static manuscript-to-Lean map and its stated limits.
- `evidence/build/` contains the final build and every-page visual-check receipts.
- `evidence/errata/` is separate from the faithful text; suspected source defects or proposed corrections belong there and are never silently applied.
- `scripts/` contains the source-preparation tool, transcription and figure audits, inventory builder, deterministic PDF builder, and figure-PDF rebuild tool.
- `MANIFEST.sha256` binds the staged repository files to exact bytes.

## Relationship to the Everyday English Edition

This repository is the source-faithful layer, not the **Everyday English Edition of the Navier–Stokes Proof**. That edition is a separate work with its own repository target, [`KokunoYumeto/navier-stokes-proof-everyday-english`](https://github.com/KokunoYumeto/navier-stokes-proof-everyday-english). It is derived from verified spans of this reconstruction while retaining exact traceability to the official PDF. Explanations or teaching additions from that edition do not belong in the faithful source here.

## Citation

For the mathematical work, cite the official OpenAI paper at the PDF link above. When referring specifically to this reconstruction, also identify [`KokunoYumeto/openai-navier-stokes-latex`](https://github.com/KokunoYumeto/openai-navier-stokes-latex) and the exact Git commit used. No `CITATION.cff` is supplied at this stage because a valid CFF record requires public author attribution that has not been established for the reconstruction; inventing or transferring attribution from the source paper would be misleading.

## Rights and reuse

The records reviewed for this project do not establish a licence for the paper or for this reconstruction. In particular, the Apache-2.0 licence in the separate Lean repository does not automatically license the paper, its figures, or this reconstructed edition. Source links and hashes document provenance; they do not grant reuse permission. See [`LICENSE-NOTICE.md`](LICENSE-NOTICE.md), and assess the rights needed for your intended use and jurisdiction.
