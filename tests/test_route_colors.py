"""CATEGORY_BY_COLOR must agree with septaclrs.csv, its provenance."""

import csv
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_septa_meta  # noqa: E402

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "septaclrs.csv")


def _rows():
    # utf-8-sig: septaclrs.csv carries a BOM, same as SEPTA's own GTFS files.
    with open(CSV_PATH, encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


class RouteColorProvenanceTest(unittest.TestCase):
    def test_csv_has_twelve_unique_rows(self):
        rows = _rows()
        self.assertEqual(len(rows), 12)
        names = [row["constantName"] for row in rows]
        self.assertEqual(len(names), len(set(names)))

    def test_category_by_color_matches_the_csv(self):
        rows = _rows()
        expected = {row["color"]: row["constantName"].lower() for row in rows}
        self.assertEqual(expected, build_septa_meta.CATEGORY_BY_COLOR)

    def test_every_constant_name_is_a_module_attribute_with_matching_value(self):
        for row in _rows():
            name = row["constantName"]
            self.assertTrue(hasattr(build_septa_meta, name),
                             f"build_septa_meta has no attribute {name}")
            self.assertEqual(getattr(build_septa_meta, name), name.lower())

    def test_hex_code_is_hash_plus_color(self):
        for row in _rows():
            self.assertEqual(row["Hex Code"], "#" + row["color"])


if __name__ == "__main__":
    unittest.main()
