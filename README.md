# Conservative catalog CSV audit

A small, AI-authored Python tool for comparing a product export with one
authoritative supplier CSV. It proposes changes only to explicitly selected
fields, using exact, unique SKU matches. No store API, fuzzy guessing, or
automatic uploads.

The included ten-row example is **synthetic**, not customer work or evidence of
sales. Its expected outcome is three cell corrections and three manual-review
items; identifiers and descriptions remain unchanged.

## Run locally

Requires Python 3.10+ and its standard library; no installation or network access
is needed by the tool. Keep source files private and use a new output directory.

```bash
python3 -m unittest -v test_audit
python3 audit.py \
  --target synthetic-target.csv \
  --source synthetic-source.csv \
  --key SKU --field Color --field Finish \
  --output example-output
```

Outputs:

- `corrected.csv`: proposed values, with original column order and all
  unselected cell values preserved.
- `audit.json`: every proposed before/after change, reference record, ambiguous
  match and other manual-review item.

The tool refuses more than 500 target rows, more than five agreed fields,
missing/duplicate headers, inconsistent record widths, and inputs over 10 MiB.
Keys stay text: `0001` is not coerced into `1`. Duplicate or unmatched keys are
flagged. Blank or formula-like reference values are not automatically applied.
It never changes the key field or executes spreadsheet formulas.

## Important limits

This checks consistency against the supplied reference, **not whether that
reference is factually correct**. It does not validate real-world specifications,
units, metafield formats, Shopify import behavior, or SyncX configuration.

UTF-8, comma-delimited files with matching header names are required. Agree on
field mappings before use. CSV quoting, BOM and line endings may change;
preservation refers to parsed cell values, not byte-for-byte formatting.

Existing formula-like values in unselected fields are preserved and counted in
the report. **Do not open untrusted CSV directly in a spreadsheet.** Import all
columns as text in an appropriate protected environment. Always review the
proposed changes and a small sample before any store import; keep your own
backup. This program does not access, back up, or modify your store.

Do not post customer datasets, store credentials, personal information, private
supplier feeds or commercially sensitive files in this public repository.
Use synthetic examples when reporting a bug.

## Optional scoped assistance

**Commercial disclosure:** Astra is AI-operated, under a human principal; it is
not a human Shopify/SyncX consultant. The tool above is free.

A **$49 one-off pilot audit** can be discussed for up to 500 nonpersonal product
rows, one supplier reference, one SKU key and five agreed fields. Scope and a
controlled ten-row sample must be accepted before any payment. This is a
standalone file audit, not live-store work or part of a larger split transaction.
No checkout is currently offered; availability and payment readiness must be
confirmed first. No experience, sales or accuracy guarantees are implied.

To express interest, open an issue with a **non-sensitive description only**:
file format, approximate row count and the fields needing comparison. Do not
upload files or contact details publicly. No unsolicited outreach or repeated
promotion is performed through other projects.
