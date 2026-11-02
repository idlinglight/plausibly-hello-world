#!/usr/bin/env python3
"""Offline checks of wikicheck's pure parts on canned API answers:
python3 -I shared/map-quiz/tools/wikicheck_test.py   (stdlib unittest)

No network: api_get is replaced by a function that fails the test. The
live check is each image's tools/wiki_titles.py, run by hand."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wikicheck  # noqa: E402

TODAY = datetime.date(2026, 11, 2)


def no_network(*_args, **_kw):
    raise AssertionError("wikicheck_test must not touch the network")


def statement(value, rank="normal", start=None, end=None, end_snak="value"):
    st = {"rank": rank, "mainsnak": {"snaktype": "value", "datavalue": {"value": {"id": value}}}}
    q = {}
    if start:
        q["P580"] = [{"snaktype": "value", "property": "P580", "datavalue": {"value": {"time": start}}}]
    if end or end_snak != "value":
        snak = {"snaktype": end_snak, "property": "P582"}
        if end:
            snak["datavalue"] = {"value": {"time": end}}
        q["P582"] = [snak]
    if q:
        st["qualifiers"] = q
    return st


QUERY = {
    "normalized": [{"from": "georgia (country)", "to": "Georgia (country)"}],
    "redirects": [
        {"from": "Ireland (state)", "to": "Republic of Ireland"},
        {"from": "Kyushu region", "to": "Kyushu", "tofragment": "Region"},
    ],
    "pages": [
        {"title": "Georgia (country)", "pageprops": {"wikibase_item": "Q230"}},
        {"title": "Republic of Ireland", "pageprops": {"wikibase_item": "Q27"}},
        {"title": "Kyushu", "pageprops": {"wikibase_item": "Q13987"}},
        {"title": "Georgia", "pageprops": {"disambiguation": "", "wikibase_item": "Q1"}},
        {"title": "Austria", "pageprops": {"wikibase_item": "Q40"}},
        {"title": "Vienna", "pageprops": {"wikibase_item": "Q1741"}},
        {"title": "Bonn", "pageprops": {"wikibase_item": "Q586"}},
        {"title": "Nowhere Land", "missing": True},
        {"title": "No item"},
    ],
}
TITLES = ["georgia (country)", "Ireland (state)", "Kyushu region", "Georgia", "Austria", "Vienna", "Bonn",
          "Nowhere Land", "No item"]
CLAIMS = {("Q40", "P36"): {"Q1741"}, ("Q183", "P36"): {"Q64"}, ("Q586", "P1376"): set(),
          ("Q1741", "P1376"): set(), ("Q99", "P36"): set(), ("Q1741x", "P1376"): set()}


class WikiCheckTest(unittest.TestCase):
    def setUp(self):
        self.saved = wikicheck.api_get
        wikicheck.api_get = no_network

    def tearDown(self):
        wikicheck.api_get = self.saved

    def test_resolve(self):
        r = wikicheck.resolve(TITLES, QUERY)
        self.assertEqual(r["georgia (country)"]["title"], "Georgia (country)")
        self.assertEqual(r["georgia (country)"]["steps"], ["normalised to 'Georgia (country)'"])
        self.assertEqual(r["Ireland (state)"]["title"], "Republic of Ireland")
        self.assertEqual(r["Ireland (state)"]["item"], "Q27")
        self.assertEqual(r["Kyushu region"]["fragment"], "Region")
        self.assertTrue(r["Georgia"]["disambiguation"])
        self.assertEqual((r["Austria"]["steps"], r["Austria"]["item"]), ([], "Q40"))
        self.assertTrue(r["Nowhere Land"]["missing"])
        self.assertIsNone(r["No item"]["item"])

    def test_current_values(self):
        sts = [
            statement("Q1"),                                            # current
            statement("Q2", rank="deprecated"),                         # deprecated
            statement("Q3", end="+1990-10-03T00:00:00Z"),               # ended
            statement("Q4", end="+2030-00-00T00:00:00Z"),               # ends later
            statement("Q5", start="+2027-01-01T00:00:00Z"),             # not yet
            statement("Q6", end_snak="somevalue"),                      # ended, date unknown
            statement("Q7", end_snak="novalue"),                        # never ends
            statement("Q8", start="+1949-05-23T00:00:00Z"),             # started long ago
            {"rank": "normal", "mainsnak": {"snaktype": "somevalue"}},  # no value to take
        ]
        self.assertEqual(wikicheck.current_values(sts, TODAY), {"Q1", "Q4", "Q7", "Q8"})
        bad = [statement("Q9", end="2020-01-01")]
        with self.assertRaisesRegex(ValueError, "'2020-01-01'.*P582"):
            wikicheck.current_values(bad, TODAY)

    def test_evaluate(self):
        info = wikicheck.resolve(TITLES, QUERY)
        entries = [
            {"key": "ok item", "title": "Austria", "item": "Q40"},
            {"key": "wrong item", "title": "Austria", "item": "Q41"},
            {"key": "normalised", "title": "georgia (country)", "item": "Q230"},
            {"key": "redirect", "title": "Ireland (state)", "item": "Q27"},
            {"key": "section", "title": "Kyushu region", "item": "Q13987"},
            {"key": "disambiguation", "title": "Georgia", "item": "Q1"},
            {"key": "missing", "title": "Nowhere Land", "item": "Q1"},
            {"key": "no item", "title": "No item", "item": "Q1"},
            {"key": "padded", "title": " Austria", "item": "Q40"},
            {"key": "underscore", "title": "Georgia_(country)", "item": "Q230"},
            {"key": "absent", "item": "Q40"},
            {"key": "capital P36", "title": "Vienna", "capital_of": "Q40"},
            {"key": "capital no", "title": "Bonn", "capital_of": "Q183"},
            {"key": "exception", "title": "Bonn", "capital_of": "Q183", "capital_item": "Q586"},
            {"key": "exception wrong", "title": "Vienna", "capital_of": "Q183", "capital_item": "Q586"},
            {"key": "exception obsolete", "title": "Vienna", "capital_of": "Q40", "capital_item": "Q1741"},
        ]
        got = {e["key"]: (ok, msg) for e, ok, msg in wikicheck.evaluate(entries, info, lambda q, p: CLAIMS[(q, p)])}
        self.assertEqual(got["ok item"], (True, "item Q40"))
        self.assertEqual(got["wrong item"], (False, "item Q40, expected Q41"))
        self.assertFalse(got["normalised"][0])
        self.assertIn("store 'Georgia (country)'", got["normalised"][1])
        self.assertEqual(got["redirect"], (False, "redirects to 'Republic of Ireland': store 'Republic of Ireland'"))
        self.assertIn("a section", got["section"][1])
        self.assertEqual(got["disambiguation"], (False, "a disambiguation page"))
        self.assertFalse(got["missing"][0])
        self.assertEqual(got["no item"], (False, "the article has no Wikidata item"))
        self.assertEqual(got["padded"], (False, "malformed title: leading, trailing or double space"))
        self.assertEqual(got["underscore"], (False, "malformed title: contains _"))
        self.assertEqual(got["absent"], (False, "malformed title: empty or not a string"))
        self.assertEqual(got["capital P36"], (True, "item Q1741, a current capital of Q40 (P36 of Q40)"))
        self.assertEqual(got["capital no"], (False, "item Q586 is no current capital of Q183 (P36 of Q183: Q64)"))
        self.assertTrue(got["exception"][0])
        self.assertNotIn("can go", got["exception"][1])
        self.assertFalse(got["exception wrong"][0])
        self.assertTrue(got["exception obsolete"][0])
        self.assertIn("the exception can go", got["exception obsolete"][1])

    def test_capital_via_p1376(self):
        info = {"Sucre": {"title": "Sucre", "steps": [], "fragment": None, "missing": False, "invalid": False,
                          "disambiguation": False, "item": "Q2907"}}
        claims = {("Q750", "P36"): {"Q1491"}, ("Q2907", "P1376"): {"Q750"}}
        [(_, ok, msg)] = wikicheck.evaluate([{"key": "BOL", "title": "Sucre", "capital_of": "Q750"}], info,
                                            lambda q, p: claims[(q, p)])
        self.assertEqual((ok, msg), (True, "item Q2907, a current capital of Q750 (P1376 of Q2907)"))

    def test_fold_and_batches(self):
        self.assertEqual(wikicheck.fold("Kingston, Jamaica"), wikicheck.fold("Kingston"))
        self.assertEqual(wikicheck.fold("Djibouti (city)"), "djibouti")
        self.assertEqual(wikicheck.fold("Saint John's"), wikicheck.fold("St. John's, Antigua and Barbuda"))
        self.assertEqual(wikicheck.fold("Kōbe"), "kobe")
        self.assertEqual([len(b) for b in wikicheck.batches(range(120))], [50, 50, 20])
        self.assertEqual(wikicheck.batches(["a", "b", "a"]), [["a", "b"]])


if __name__ == "__main__":
    unittest.main()
