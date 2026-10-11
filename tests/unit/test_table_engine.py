# -*- coding: utf-8 -*-
"""Guard rails for the reusable table engine and its central stylesheet.

These assert the CONTRACT the console depends on, in the two central files, so
a regression cannot come back silently:

  * every column gets a resize handle and a sort affordance,
  * sorting is wired to a header click on both table families,
  * a wide table is given a real scroll frame (overflow-x) instead of pushing
    the page sideways,
  * resize updates the header AND the body cells together,
  * the stylesheet defines a scroll rule for the wrapper class the engine adds.

The browser-level behaviour (actual sorting, dragging, scrolling) is proved by
scripts/verify_table_engine.py, which drives a real browser.
"""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS = os.path.join(ROOT, "webui", "assets", "alp-table.js")
CSS = os.path.join(ROOT, "webui", "assets", "alp-table.css")
HTML = os.path.join(ROOT, "webui", "index.html")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class TestTableEngineJs(unittest.TestCase):

    def setUp(self):
        self.src = read(JS)

    def test_engine_is_self_contained_and_balanced(self):
        self.assertEqual(self.src.count("{"), self.src.count("}"))
        self.assertEqual(self.src.count("("), self.src.count(")"))
        self.assertIn("window.AlpTableEngine = AlpTableEngine", self.src)

    def test_both_table_families_are_supported(self):
        for needle in (".table-container", "ember-table-header-cell",
                       "me-table", "me-authentic-table"):
            self.assertIn(needle, self.src, needle)

    def test_standard_tables_get_a_resize_handle_per_column(self):
        self.assertIn("'alp-col-resizer'", self.src)
        # handle is added once per column, guarded against double-insertion
        self.assertIn("if (!th.querySelector('.alp-col-resizer'))", self.src)

    def test_sorting_is_bound_to_the_header_click(self):
        self.assertIn("cell.addEventListener('click'", self.src)
        self.assertIn("th.addEventListener('click'", self.src)

    def test_clicking_the_resizer_does_not_also_sort(self):
        # A drag that ends over the header must not re-sort the column.
        self.assertIn("e.target.closest('.alp-col-resizer')", self.src)

    def test_binding_is_idempotent(self):
        # The MutationObserver re-enhances constantly; a second bind would
        # double every sort.
        self.assertIn("cell._alpSortBound", self.src)
        self.assertIn("th._alpSortBound", self.src)

    def _method(self, name, length=2500):
        """Slice a single method body, not the first textual mention.

        The engine's methods call each other, so searching for a method name
        finds the CALL site long before the definition.
        """
        i = self.src.index("%s(" % name)
        while i > 0 and self.src[max(0, i - 8):i].strip().endswith("this."):
            i = self.src.index("%s(" % name, i + 1)
        return self.src[i:i + length]

    def test_resize_updates_header_and_body_together(self):
        body = self._method("onMouseMove")
        self.assertIn("targetCell", body, "body cells must follow the header")
        self.assertIn("minWidth", body)

    def test_resize_has_a_minimum_width(self):
        self.assertIn("Math.max(50", self.src,
                      "a column must not be draggable to zero width")

    def test_standard_table_wrapper_gets_overflow_x(self):
        body = self._method("enhanceStandardTable")
        self.assertIn("alp-table-scroll", body,
                      "the wrapper the engine adds needs a scroll frame class")
        self.assertIn("overflowX", body)

    def test_comparison_handles_numbers_and_text(self):
        body = self._method("compareValues")
        self.assertIn("localeCompare", body)
        self.assertIn("numA - numB", body,
                      "numeric columns must sort numerically, not as text")
        self.assertIn("numeric: true", body)

    def test_sort_state_is_per_table(self):
        self.assertIn("new WeakMap()", self.src,
                      "sort state must not leak between tables")


class TestTableStylesheet(unittest.TestCase):

    def setUp(self):
        self.css = read(CSS)

    def test_stylesheet_is_balanced(self):
        self.assertEqual(self.css.count("{"), self.css.count("}"))

    def test_scroll_frame_rule_exists(self):
        # .tw / .alp-table-scroll must own the horizontal overflow; without a
        # rule the engine wraps the table but nothing scrolls.
        for cls in (".alp-table-scroll", ".tw"):
            self.assertIn(cls, self.css, cls)
        i = self.css.index(".alp-table-scroll")
        rule = self.css[i:self.css.index("}", i)]
        self.assertIn("overflow-x: auto", rule)

    def test_ember_container_scrolls(self):
        i = self.css.index(".table-container")
        rule = self.css[i:self.css.index("}", i)]
        self.assertIn("overflow-x: auto", rule)

    def test_table_keeps_natural_width_inside_the_frame(self):
        self.assertIn("max-content", self.css,
                      "columns must not be squashed to fit; the frame scrolls")

    def test_sort_and_resize_affordances_are_styled(self):
        for sel in (".alp-col-resizer", ".alp-sort-arrow", ".sortable",
                    ".active-sort"):
            self.assertIn(sel, self.css, sel)

    def test_ember_and_standard_share_the_stylesheet(self):
        self.assertIn(".me-table th.sortable", self.css)
        self.assertIn(".ember-table-header-cell.sortable", self.css)


class TestTableWiring(unittest.TestCase):

    def test_assets_are_loaded_by_the_page(self):
        html = read(HTML)
        self.assertIn("assets/alp-table.js", html)
        self.assertIn("assets/alp-table.css", html)

    def test_engine_runs_on_dom_ready(self):
        src = read(JS)
        self.assertTrue("DOMContentLoaded" in src or "readyState" in src,
                        "the engine must attach itself when the page loads")

    def test_dynamic_tables_are_enhanced(self):
        self.assertIn("MutationObserver", read(JS),
                      "the console renders tables after load")


if __name__ == "__main__":
    unittest.main()