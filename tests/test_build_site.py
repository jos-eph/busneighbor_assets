"""Unit tests for build_site. Stdlib only, no network."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_site  # noqa: E402


class ExpandIncludesTest(unittest.TestCase):
    def setUp(self):
        self.partials = Path(tempfile.mkdtemp())
        (self.partials / "piece.html").write_text("<p>one</p>\n\n<p>two</p>\n", encoding="utf-8")

    def expand(self, text):
        return build_site.expand_includes(text, self.partials)

    def test_replaces_marker_with_indent(self):
        self.assertEqual(self.expand("<main>\n  <!-- #include piece.html -->\n</main>"),
                         "<main>\n  <p>one</p>\n\n  <p>two</p>\n</main>")

    def test_unknown_partial_fails(self):
        with self.assertRaisesRegex(ValueError, "unknown partial"):
            self.expand("<!-- #include missing.html -->")

    def test_nested_include_fails(self):
        (self.partials / "outer.html").write_text("<!-- #include piece.html -->", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "nesting"):
            self.expand("<!-- #include outer.html -->")

    def test_marker_not_alone_on_its_line_fails(self):
        with self.assertRaisesRegex(ValueError, "not replaced"):
            self.expand("<p>x <!-- #include piece.html --></p>")

    def test_path_outside_partials_is_not_a_marker(self):
        with self.assertRaisesRegex(ValueError, "not replaced"):
            self.expand("<!-- #include ../secret.html -->")


class RealPagesTest(unittest.TestCase):
    """The site's own pages assemble, and each carries the shared footer."""

    def test_pages_assemble(self):
        out = Path(tempfile.mkdtemp())
        build_site.build(out)
        for page in build_site.PAGES:
            text = (out / page).read_text(encoding="utf-8")
            self.assertNotIn("#include", text, page)
            self.assertIn("not affiliated with, endorsed by, or operated by SEPTA", text, page)
            self.assertEqual(text.count("<footer>"), 1, page)

    def test_store_badges_on_pages_that_offer_the_app(self):
        out = Path(tempfile.mkdtemp())
        build_site.build(out)
        for page in ("index.html", "go.html"):
            text = (out / page).read_text(encoding="utf-8")
            self.assertIn("apps.apple.com/app/busneighbor/id6812131455", text, page)
            self.assertIn("details?id=org.dydx.busneighbor_flutter", text, page)


if __name__ == "__main__":
    unittest.main()
