import csv
from pathlib import Path
import tempfile
import unittest

from audit import compare, load_csv


class AuditTests(unittest.TestCase):
    headers = ["SKU", "Color", "SEO"]

    def compare(self, targets, sources, fields=None):
        return compare(self.headers, targets, self.headers, sources, "SKU", fields or ["Color"])

    def row(self, sku="0001", color="red", seo="Keep original SEO"):
        return {"SKU": sku, "Color": color, "SEO": seo}

    def test_only_agreed_cell_changes_and_leading_zero_retained(self):
        old = self.row()
        corrected, report = self.compare([old], [self.row(color="blue", seo="Never copy this")])
        self.assertEqual(corrected, [self.row(color="blue")])
        self.assertEqual(old, self.row())
        self.assertTrue(report["unapproved_fields_preserved"])
        self.assertEqual(report["changes"][0]["before"], "red")
        self.assertEqual(report["changes"][0]["source_record"], 2)

    def test_duplicates_and_absent_keys_not_guessed(self):
        targets = [self.row("0001"), self.row("0002"), self.row("0002"), self.row("9999")]
        source = [self.row("0001", "blue"), self.row("0001", "green"), self.row("0002", "blue")]
        corrected, report = self.compare(targets, source)
        self.assertEqual(corrected, targets)
        self.assertEqual([item["reason"] for item in report["manual_review"]],
                         ["duplicate_source_key", "duplicate_target_key", "duplicate_target_key", "unmatched_key"])

    def test_whitespace_not_silently_normalized(self):
        corrected, report = self.compare([self.row(" 0001")], [self.row("0001", "blue")])
        self.assertEqual(corrected[0]["Color"], "red")
        self.assertEqual(report["manual_review"][0]["reason"], "empty_or_whitespace_key")

    def test_blank_reference_and_formula_like_values_flagged(self):
        for value in ("", " ", "=SUM(1,2)", "+123", "-1", "@item", " \t=1"):
            corrected, report = self.compare([self.row()], [self.row(color=value)])
            self.assertEqual(corrected[0]["Color"], "red")
            self.assertEqual(len(report["manual_review"]), 1)

    def test_existing_formula_like_data_preserved_and_warned(self):
        corrected, report = self.compare([self.row(seo="=untrusted")], [self.row(color="blue")])
        self.assertEqual(corrected[0]["SEO"], "=untrusted")
        self.assertEqual(report["formula_like_cells_retained"], 1)

    def test_scope_key_and_field_errors(self):
        for fields in (["SKU"], ["missing"], ["Color", "Color"]):
            with self.assertRaises(ValueError):
                self.compare([self.row()], [self.row()], fields)
        with self.assertRaises(ValueError):
            self.compare([self.row()] * 501, [self.row()])

    def test_identical_files_produce_no_changes(self):
        _, report = self.compare([self.row()], [self.row()])
        self.assertEqual(report["changes"], [])
        self.assertEqual(report["manual_review"], [])

    def test_quoted_csv_unicode_multiline_and_invalid_shape(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fixture.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(self.headers)
                writer.writerow(["0001", "blue, bright", "line one\nline two"])
            headers, rows = load_csv(path)
            self.assertEqual(headers, self.headers)
            self.assertEqual(rows[0]["SKU"], "0001")
            self.assertEqual(rows[0]["SEO"], "line one\nline two")
            for text in ("SKU,Color,Color\n1,a,b\n", "SKU,Color\n1,a,extra\n", ""):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    load_csv(path)


if __name__ == "__main__":
    unittest.main()
