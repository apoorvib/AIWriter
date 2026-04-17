# Outline fixtures

Small PDFs used to test the outline extractor. Each fixture is checked in
because regeneration is cumbersome and the files are under ~200KB.

| File | How it was made |
|------|-----------------|
| `born_digital_with_outlines.pdf` | 30-page ReportLab PDF with 3 chapters, each registered via `canvas.bookmarkPage` + `canvas.addOutlineEntry`. See `make_fixtures.py` at the bottom of this README. |
| `page_labels_only.pdf` | Same content as above, but regenerated with `/PageLabels` set to 5 Roman + 25 Arabic pages, and outlines stripped. |
| `article_no_toc.pdf` | 10-page ReportLab PDF with body text only, no outline, no labels, no TOC page. |
| `scanned_book_fragment.pdf` | 8-page PDF of page-images from an out-of-copyright text (Federalist Papers no. 10, Project Gutenberg). Simulates a scanned book. |

## Regenerating

See `tests/outline/fixtures/make_fixtures.py` for the generator script. Run
`python tests/outline/fixtures/make_fixtures.py` to rebuild them.
