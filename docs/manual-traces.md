# Manually supplied traces

Keep the original JSONL outside this repository. Import a selected, single-request Claude Tag trace with:

```bash
uv run python scripts/import_manual_trace.py /path/to/selected-request.jsonl YYYY-MM-DD
uv run phistory render-index
uv run phistory translate --agents claude-tag --all-captured --prune
uv run phistory build-site --output .phistory-cache/site
uv run python scripts/audit_translations.py --site-dir .phistory-cache/site --require-complete
```

The importer applies the same policy to every version. It retains system instructions, interleaved system reminders, tool definitions, and cache boundaries; replaces private memory payloads, session links, emails, runtime paths, and transport identifiers with stable placeholders; removes the captured user text and later conversation content. Later non-system messages become one history placeholder, with their count recorded in `meta.json`. The original file's SHA-256 is recorded there too. `trace.jsonl` in the archive is redacted evidence, not a byte-for-byte copy of the source.

Review the resulting `prompt.md` and its diff before publishing. New source shapes or private data types may need a shared importer rule and a regression test. Do not add a version-specific replacement for a value that occurs across versions.
