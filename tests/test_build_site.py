"""Unit tests for build_site. Stdlib only, no network."""

import json
import os
import re
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

    def test_footer_links_to_the_link_maker(self):
        out = Path(tempfile.mkdtemp())
        build_site.build(out)
        for page in build_site.PAGES:
            text = (out / page).read_text(encoding="utf-8")
            self.assertIn('<a href="/share.html">Route links</a>', text, page)

    def test_homepage_links_to_route_pages_and_the_link_maker(self):
        text = (build_site.ROOT / "index.html").read_text(encoding="utf-8")
        self.assertRegex(text, r'href="/route/[A-Za-z0-9_-]+"')
        self.assertIn('href="/routes.html"', text)
        self.assertIn('href="/share.html"', text)

    def test_structured_data_parses(self):
        for page in ("index.html", "share.html"):
            text = (build_site.ROOT / page).read_text(encoding="utf-8")
            blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
            self.assertEqual(len(blocks), 1, page)
            json.loads(blocks[0])

    def test_link_maker_explains_itself_without_javascript(self):
        text = (build_site.ROOT / "share.html").read_text(encoding="utf-8")
        self.assertIn('<meta property="og:image"', text)
        self.assertIn('<h2 id="how">How it works</h2>', text)
        self.assertIn('<h2 id="questions">Questions</h2>', text)

    def test_store_badges_on_pages_that_offer_the_app(self):
        out = Path(tempfile.mkdtemp())
        build_site.build(out)
        for page in ("index.html", "go.html"):
            text = (out / page).read_text(encoding="utf-8")
            self.assertIn("apps.apple.com/app/busneighbor/id6812131455", text, page)
            self.assertIn("details?id=org.dydx.busneighbor_flutter", text, page)


if __name__ == "__main__":
    unittest.main()
