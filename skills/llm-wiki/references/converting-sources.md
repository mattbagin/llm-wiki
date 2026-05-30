# Converting Sources to Markdown — Reference

`tools/convert.py` turns web pages, `.docx`, `.pdf`, and other office formats into Markdown
so they can be ingested into the wiki. It is used directly (CLI) and automatically by
`research.py ingest --file` for non-text inputs.

## Usage

```bash
python tools/convert.py https://example.com/article        # → stdout
python tools/convert.py report.docx -o raw/documents/report.md
python tools/convert.py paper.pdf   -o raw/pdf/paper.md
```

`.md` / `.markdown` / `.txt` inputs pass through unchanged.

## Conversion strategy (primary + graceful fallback)

The converter prefers **Microsoft `markitdown`** — one library that handles
docx/pdf/pptx/xlsx/html/images and produces LLM-friendly markdown. If markitdown isn't
installed (or fails on a file), it falls back to focused libraries so it still works on
locked-down machines:

| Input | Primary | Fallback |
|-------|---------|----------|
| `.docx` | markitdown | `mammoth` → markdown, else `python-docx` → text |
| `.pdf` | markitdown | `pdfplumber`, else `pypdf` |
| `.html` / `.htm` | markitdown | `research.py` HTML→text extractor |
| URL | markitdown (if it fetches) | `research.fetch_url` (or raw `httpx` + extractor) |

## Installing converters

```bash
pip install markitdown            # preferred — covers all formats
pip install mammoth pdfplumber    # fallbacks for .docx / .pdf
```

If none is available for a given format, `convert.py` exits with an actionable message
telling you which package to install. On a machine where you can't install anything,
save the source as `.txt`/`.md` by hand and ingest that.

## How ingest uses it

`research.py run_file_ingest_pipeline` checks the file suffix:
- text/markdown → read directly
- anything else → `convert.convert(path)` first, then summarize + draft wiki updates

So `python tools/research.py ingest --file contract.pdf` converts and ingests in one step.

## Extending

`convert.py` is small and dependency-light by design. To support a new format, add a branch
in `convert()` and a `_<fmt>_fallback()` helper following the existing pattern (lazy import,
clear error if the library is missing).
