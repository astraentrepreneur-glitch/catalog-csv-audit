"""Conservative CSV comparison: exact unique keys, explicit fields, no live-store access."""

import argparse
from collections import Counter, defaultdict
import csv
import json
import os
from pathlib import Path

MAX_TARGET_ROWS = 500
MAX_FIELDS = 5
MAX_FILE_BYTES = 10 * 1024 * 1024


def load_csv(path):
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Input exceeds the 10 MiB pilot limit; review scope before proceeding.")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        try:
            headers = next(reader)
        except StopIteration:
            raise ValueError("CSV is empty.") from None
        if not headers or any(not name.strip() for name in headers) or len(set(headers)) != len(headers):
            raise ValueError("CSV needs nonempty, unique headers.")
        rows = []
        for record, values in enumerate(reader, 2):
            if len(values) != len(headers):
                raise ValueError(f"Record {record} has an unexpected number of columns.")
            rows.append(dict(zip(headers, values)))
    return headers, rows


def formula_like(value):
    return value.lstrip().startswith(("=", "+", "-", "@"))


def compare(target_headers, target, source_headers, source, key, fields):
    if not fields or len(fields) > MAX_FIELDS or len(fields) != len(set(fields)):
        raise ValueError("Agree on one to five distinct fields.")
    if key in fields:
        raise ValueError("The matching key cannot be a correction field.")
    if any(name not in headers for headers in (target_headers, source_headers) for name in [key, *fields]):
        raise ValueError("Key and agreed fields must exist in both files; map names explicitly first.")
    if len(target) > MAX_TARGET_ROWS:
        raise ValueError("Target exceeds the 500-row pilot scope.")
    index = defaultdict(list)
    for record, row in enumerate(source, 2):
        index[row[key]].append((record, row))
    counts = Counter(row[key] for row in target)
    corrected = [row.copy() for row in target]
    changes, review = [], []
    for record, (old, new) in enumerate(zip(target, corrected), 2):
        sku = old[key]
        item = {"target_record": record, "key": sku}
        if not sku or sku != sku.strip():
            review.append({**item, "reason": "empty_or_whitespace_key"})
            continue
        if counts[sku] != 1:
            review.append({**item, "reason": "duplicate_target_key"})
            continue
        matches = index.get(sku, [])
        if len(matches) != 1:
            review.append({**item, "reason": "unmatched_key" if not matches else "duplicate_source_key"})
            continue
        source_record, reference = matches[0]
        for field in fields:
            value = reference[field]
            if old[field] == value:
                continue
            if not value.strip() or formula_like(value):
                review.append({**item, "field": field, "reason":
                               "blank_source_value" if not value.strip() else "formula_like_source_value"})
                continue
            new[field] = value
            changes.append({**item, "source_record": source_record, "field": field,
                            "before": old[field], "after": value})
    preserved = all(before[field] == after[field]
                    for before, after in zip(target, corrected)
                    for field in target_headers if field not in fields)
    if not preserved:
        raise AssertionError("Unapproved field changed.")
    report = {
        "method": "exact_unique_key; explicit field list; source supplied by customer",
        "key_field": key, "agreed_fields": fields,
        "target_rows": len(target), "source_rows": len(source),
        "changes": changes, "manual_review": review,
        "unapproved_fields_preserved": preserved,
        "formula_like_cells_retained": sum(formula_like(value) for row in corrected for value in row.values()),
        "limitations": [
            "Source correctness, units and real-world product specifications are not independently verified.",
            "No fuzzy matches, blank-value deletion, formula execution, or live store changes.",
            "CSV serialization may change quoting/BOM/line endings; cell values outside agreed fields are preserved.",
            "Import CSV columns as text; do not open untrusted CSV directly in a spreadsheet.",
            "Customer must review the sample and proposed changes before any store import.",
        ],
    }
    return corrected, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--field", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target_headers, target = load_csv(args.target)
    source_headers, source = load_csv(args.source)
    corrected, report = compare(target_headers, target, source_headers, source, args.key, args.field)
    os.umask(0o077)
    # A new output directory prevents accidental replacement of inputs or prior deliverables.
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    with (args.output / "corrected.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=target_headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(corrected)
    (args.output / "audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(target), "changed_cells": len(report["changes"]),
                      "review_items": len(report["manual_review"]),
                      "unapproved_fields_preserved": report["unapproved_fields_preserved"]}))


if __name__ == "__main__":
    main()
