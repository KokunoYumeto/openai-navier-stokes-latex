# Finite Time Blowup for Navier–Stokes: Independent LaTeX Reconstruction

[Read the 166-page transcription PDF](output/pdf/source-faithful-reconstruction.pdf) · [Browse the LaTeX](reconstruction/) · [Read OpenAI’s original paper](https://cdn.openai.com/pdf/32d9f210-8b73-45e0-91bc-82a30aef8a9a/navier-stokes.pdf)

This repository contains an independently prepared LaTeX transcription of OpenAI’s *Finite Time Blowup for Navier–Stokes*. The document includes the paper’s main text, appendices and bibliography in 29 section files, together with its style file, six figure assets and a 166-page reading PDF. Its page markers follow the original paper’s pages 1–166.

The transcription is intended to reproduce OpenAI’s actual wording and mathematics, including any irregularities in the original. Mathematical criticism, supplementary proofs and proposed mathematical corrections belong in separate works. OpenAI’s PDF is the transcription authority; this repository is an independent reconstruction, not an official author-source release.

## Reading and comparison

Comparison with the original is ongoing. Full fidelity of the present transcription has not been established. The [current source-comparison status](evidence/transcription/TRANSCRIPTION_AUDIT.json) identifies the exact formulas and symbols compared with the original. The [formula index](evidence/transcription/FORMULA_INVENTORY.json) and [page index](evidence/transcription/PDF_TEX_CORRESPONDENCE.json) locate the editable text; they are navigation aids, not proof of fidelity.

The [current document-build record](evidence/build/CURRENT_DOCUMENT.json) identifies the supplied PDF and the pages inspected in it. Its 166 pages contain extractable text, and its build resolves the internal references. These checks do not verify every transcription detail or establish the paper’s theorem. Evidence records apply only to the files and scope they identify.

The original PDF used for comparison has SHA-256 `0e779481c4da40bd28d1e642e1d8ca57447d129610df28dfa5a11e9af8ae228f`. The [manifest](MANIFEST.sha256) identifies repository files. The [archival source-edition family](https://doi.org/10.5281/zenodo.22852309) is available separately.

## Build

Open [reconstruction/main.tex](reconstruction/main.tex). A TeX installation needs the packages listed in [ns-edition.sty](reconstruction/ns-edition.sty), including the AMS packages, `mathtools`, `mathpazo`, `mathrsfs`, `graphicx`, `microtype`, `enumitem`, `geometry`, `fancyhdr`, `hyperref` and `cleveref`.

From the `reconstruction` directory, run:

```text
pdflatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex
pdflatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex
```

The result is `main.pdf`. Exact PDF bytes can depend on the TeX engine, fonts and package versions. The repository also supplies source-comparison and inventory tools under `scripts/`.

## Related works, citation and rights

The [Everyday English edition](https://github.com/KokunoYumeto/navier-stokes-proof-everyday-english) is a separate experimental exposition. The [Navier–Stokes workbench](https://github.com/KokunoYumeto/yang-mills-interacting-workbench/tree/main/navier-stokes) contains separate analytical material. Neither is a substitute for the original paper or a certificate of its theorem.

For the mathematics, cite OpenAI’s paper. When referring to this transcription, identify this repository and the exact Git revision used. The [rights notice](LICENSE-NOTICE.md) accompanies the source and figure assets; no additional licence is inferred from a related repository.
