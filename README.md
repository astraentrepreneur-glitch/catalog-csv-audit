# Catalog Audit — local self-serve CSV comparison

**Free source MVP · AI-authored · MIT licensed · Python 3.10+ standard library**

Compare a catalog export with a reference CSV, choose an exact matching key and
up to five correction fields, then download proposed corrections and an audit.
Repeat runs yourself: no agent, consultant, account, checkout or installation
required. This is a repeatable software prototype, not a bespoke audit service.
The payment model and demand for future paid convenience features are unvalidated.
There is no paid exclusive license over this MIT code, and no hosting, updates
or support commitment.

## Browser workflow

From this directory:

```bash
python3 app.py
```

Open the **exact `http://127.0.0.1:PORT/` URL printed in your terminal**.
The OS chooses an available port; optionally use `python3 app.py --port 8765`.
The app binds only to `127.0.0.1`, never opens a browser automatically, and stops
with Ctrl+C. Do not expose it through a proxy, tunnel or public server.

1. Choose target and source CSV files, then **Inspect columns**.
2. Review the row/column counts and common columns. Select the matching key
   and **one to five distinct correction fields**. No correction fields are
   selected for you.
3. Choose **Create proposed corrections**. Review summary counts, then download
   the ZIP and inspect its three files:
   - `corrected.csv`: proposed values, original column order, unselected cell
     values and key preserved.
   - `audit.json`: every proposed change, reference record and manual-review
     item, plus limitations.
   - `changes.csv`: machine-readable projection of the report's changes, with
     `target_record,key,source_record,field,before,after` columns.

The included ten-row files are **synthetic**, not customer work or sales evidence.
Select `synthetic-target.csv`, `synthetic-source.csv`, key `SKU`, fields `Color`
and `Finish`: expect **3 proposed cell changes and 3 manual-review items**.
Review items are not necessarily distinct rows; one row may have several items.

## Privacy boundary

The browser sends file contents as base64 JSON **over loopback HTTP to the local
Python process**, once for inspection and again for comparison. This is a local
transfer, not a cloud upload or a claim that data never leaves browser memory.
Comparison uses the same Python engine as the CLI; JavaScript does not compare
CSV cells. No dependencies, external network requests, analytics or live-store
connections are used.

The server does not save uploads or retain datasets between requests. Browser
memory retains selected inputs/results until replaced or the page closes; the
browser writes a ZIP only when you download it. OS swap, crash dumps, browser
extensions, browser download history and other software are outside this app's
control; this is not a secure-erasure guarantee.

Requests require a random per-server token, the exact bound Host and same Origin.
There is no CORS; assets are allowlisted, responses disable caching, and the CSP
allows no remote assets. Body reads have size/time bounds. Request bodies, tokens
and filenames are not logged. These protections do not defend against malicious
software or other users who already control your computer. Close the page and
stop the server after use.

## Conservative behavior and important warnings

- At most **500 target rows**, **5 distinct correction fields**, **10 MiB per
  file**. Source rows have no separate count cap; the file-size limit applies.
- UTF-8 (optional BOM), comma-delimited files with nonempty unique headers and
  consistent record widths are required. Malformed input is rejected. Python's
  CSV parser also imposes its default per-field size limit (normally 128 KiB).
- Keys stay strings: `0001` is not `1`. No fuzzy matching, trimming, case folding,
  unit conversions or inferred header mapping. Duplicate, blank, whitespace and
  unmatched keys require manual review.
- Blank or formula-like differing source values are flagged instead of copied.
  The key and unselected cell values remain unchanged. CSV quoting, BOM and line
  endings may change: this is cell-value preservation, not byte-for-byte copying.
- **Source correctness is not independently verified.** This does not validate
  product facts, units, metafield formats or any platform's import behavior.
- **Neither CSV is sanitized or guaranteed safe for spreadsheets or live-store
  import.** Existing formula-like cells remain in `corrected.csv`; before/after
  values and keys can also appear in `changes.csv`. Never open untrusted CSV
  directly in a spreadsheet. Use a protected text-import workflow, review all
  proposals and a sample, and keep your own backups before considering import.
- AI-authored software may contain errors. No accuracy or sales guarantees.
  The app cannot access, back up or modify your store.

This first increment has no installer, saved configurations, batch jobs, cloud
hosting, authentication for multiple users or checkout. It is a single-user,
single-request-at-a-time local app; a bounded slow request may briefly delay
other requests. A modern browser with JavaScript and a Python runtime is required.

## Existing CLI

The original arguments remain compatible; `changes.csv` is an additive output.
Use a new output directory (existing directories are not overwritten).

```bash
python3 audit.py \
  --target synthetic-target.csv \
  --source synthetic-source.csv \
  --key SKU --field Color --field Finish \
  --output example-output
```

## Worked example: review a recurring supplier update

Use this workflow when two small files share an exact identifier and you want
to inspect proposed price/stock changes **before deciding whether to import**.
A store's native importer may already support identifier matching; this example
is about an offline before/after report, not a missing native-import feature.
The 500-target-row and matching-header limits still apply.

The following fixtures are entirely **synthetic**. Their identifier strings
are not validated GTINs, and the headers are not a platform import template.
Use the current `main`
[source ZIP](https://github.com/astraentrepreneur-glitch/catalog-csv-audit/archive/refs/heads/main.zip)
or checkout for the included `examples/` directory. The older `v0.1.0-preview`
ZIP does not include these fixtures; its unchanged engine can run them if
downloaded separately from the links below. Save the raw CSVs, not GitHub's
HTML previews, in an `examples/` directory beside the Python files.

| File | Purpose |
| --- | --- |
| [supplier-target.csv](examples/supplier-target.csv) | Two merchant-like rows with internal ID, SKU, GTIN, price and stock |
| [supplier-reference.csv](examples/supplier-reference.csv) | One supplier-like row with the same GTIN header and updated price/stock |

In the browser workflow, select these files, key **GTIN**, and fields **Price**
and **Stock**. Or, from the source directory, use a new output directory:

```bash
python3 audit.py \
  --target examples/supplier-target.csv \
  --source examples/supplier-reference.csv \
  --key GTIN --field Price --field Stock \
  --output supplier-example-output
```

Expected result: **2 proposed cell changes and 1 manual-review item**.
For `SKU-A`, price changes from `12.00` to `12.50` and stock from `4` to `7`.
`SKU-B` has no reference match and remains unchanged, with a review item.
Both internal IDs, both SKUs and all leading zeros in GTIN strings stay intact.
The output also contains `audit.json` and a two-change `changes.csv`.

To see repeat-run behavior, compare the proposed output to the **same** reference:

```bash
python3 audit.py \
  --target supplier-example-output/corrected.csv \
  --source examples/supplier-reference.csv \
  --key GTIN --field Price --field Stock \
  --output supplier-repeat-output
```

Expect **0 further changes and still 1 review item**: the unmatched record has
not been resolved. This does not demonstrate unattended synchronization.
For a later real supplier update, choose the new reference and a fresh,
reviewed target export yourself; there is no scheduler or live-store connection.
Source accuracy, currency, tax, units, GTIN validity and import compatibility
are not checked. Keep backups and review proposals; neither output CSV is
guaranteed spreadsheet-safe or import-safe.

Does this match a recurring workflow? A
[public issue](https://github.com/astraentrepreneur-glitch/catalog-csv-audit/issues/new)
can describe synthetic header names, approximate row count, update frequency and
which repeated step would be worth paying to automate. Do not post customer
data or private supplier files. This is voluntary product research, not a
promise to build a feature or provide paid support.

## Tests and source distribution

```bash
python3 -m unittest -v test_audit test_app
```

Tests use synthetic data and an ephemeral loopback HTTP server that shuts down
afterward; they need no internet or packages. HTTP tests cover parsing, selection,
ZIP results, input bounds and request defenses. They do not replace a real
browser interaction check.

A source distribution needs only this deterministic allowlist (sorted):
`LICENSE`, `README.md`, `app.js`, `app.py`, `audit.py`,
`examples/supplier-reference.csv`, `examples/supplier-target.csv`,
`index.html`, `style.css`,
`synthetic-source.csv`, `synthetic-target.csv`, `test_app.py`, `test_audit.py`.
Exclude caches, downloads, outputs, private datasets and workstation state.
Nothing here is published automatically.

Do not submit customer datasets, credentials, personal information or private
supplier feeds to public issues. Bug reports should use synthetic examples only.
