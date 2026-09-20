# Bounded official LaTeX-source search

- Record ID: `NS-SOURCE-SEARCH-20260919-001`
- Audit window: 2026-09-19 23:34--23:38 CEST (21:34--21:38 UTC)
- Search scope: public OpenAI-controlled announcement and indexed site pages; the linked official GitHub repository, all of its public branches/tags/releases and both historical commit trees; and a bounded set of plausible source-archive names beside the official CDN PDF
- Result: no complete manuscript LaTeX/source release was found in this defined scope

## Exact public entry points

1. `https://openai.com/index/navier-stokes-solution/`
   - The publication page exposes `Read the paper`, linking the PDF, and `Link to Lean formalized proof`, linking `openai/NavierStokesAndEuler`.
   - It exposes no TeX, source archive, supplemental-source, or repository link other than the Lean repository.
   - The frozen HTML was searched case-insensitively for `latex`, `tex`, `source`, `paper`, `github`, `download`, `zip`, and `supplement` in context.
2. `https://openai.com/sitemap.xml`
   - All 42 child sitemaps available during the audit were fetched.
   - Case-insensitive URL matching for `navier`, `stokes`, or `blowup` found only the announcement URL, repeated in the publication and research sitemap groupings; no separate source-release page was indexed.
3. `https://github.com/openai/NavierStokesAndEuler`
   - `git ls-remote --symref`, `--heads`, and `--tags` showed only branch `main`, at `f9e8bc5b38b6e212696e8a30e3e91517af887bbd`, and no tags.
   - GitHub's REST endpoints returned one branch, zero tags, and zero releases/assets. The releases page said that no releases exist.
   - The repository has exactly two commits. Complete recursive path enumeration found 2,669 files at `f9e8bc5...` and 2,496 files at parent `8937a8f...`.
   - In both complete commit trees, zero paths matched `.tex`, `.ltx`, `.sty`, `.cls`, `.bib`, `.dtx`, `.ins`, `.pdf`, `.zip`, `.tar`, `.tar.gz`, `.tgz`, `.gz`, `.7z`, or `.rar`.
   - The current README calls the repository a Lean 4 formalization and links the externally hosted PDF. `formalization.yaml` likewise identifies the PDF URL as the analytical source.
   - GitHub repository searches `org:openai navier stokes` and `org:openai NavierStokes` returned only `openai/NavierStokesAndEuler`; `org:openai "Finite time blowup"` returned no repository. Unauthenticated GitHub code-search API returned HTTP 401 and is explicitly not counted as negative evidence.
4. Official PDF/CDN location
   - `navier-stokes.pdf` returned HTTP 200 and is the exact 2,959,204-byte, 166-page PDF recorded in `SOURCE_FREEZE.json`.
   - `pdfdetach -list` reported zero embedded files. `pdfinfo` and the PDF info object identify LaTeX/pdfTeX as the producing software, but that does not supply source.
   - Bounded sibling-name `HEAD` probes returned HTTP 404 for `navier-stokes.tex`, `navier-stokes.zip`, `navier-stokes-source.zip`, `source.zip`, `navier-stokes.tar.gz`, and `supplement.zip`.

## Exact search queries

- `site:openai.com "Finite Time Blowup for Navier–Stokes" LaTeX source`
- `site:github.com/openai/NavierStokesAndEuler (tex OR latex OR source OR supplement)`
- `site:github.com/openai "Finite Time Blowup for Navier-Stokes"`
- `site:cdn.openai.com/navier-stokes (tex OR source OR zip)`
- domain-restricted variants of `"Finite time blowup for Navier–Stokes" source`, `"Finite time blowup for Navier–Stokes" LaTeX`, and `"navier-stokes.pdf" source code`
- `repo:openai/NavierStokesAndEuler extension:tex`

The official results resolved to the announcement, the PDF, the Lean repository, and `formalization.yaml`; none supplied manuscript source. Unofficial mirrors and commentary were excluded from the authority decision.

## Bounded conclusion and operational decision

No complete paper source was found on the listed public, indexed official surfaces during the stated audit window. This does **not** prove that source does not exist on a private, unindexed, differently named, or future endpoint. It is sufficient for the task's required bounded official search.

Production therefore proceeds as an explicitly labeled independent source-faithful reconstruction from the frozen official PDF. If OpenAI later releases verifiable complete source, it must be frozen and compared before it can supersede any reconstructed span.
