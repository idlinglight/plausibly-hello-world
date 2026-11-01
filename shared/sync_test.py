#!/usr/bin/env python3
"""Checks of shared/sync.py on scratch repositories (stdlib unittest):
python3 -I shared/sync_test.py"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync  # noqa: E402


def write(root, rel, text):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def readt(root, rel):
    p = os.path.join(root, *rel.split("/"))
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return fh.read()


RULES = {
    "rules": [
        {"from": "nginx.conf", "to": "nginx.conf", "images": "*"},
        {"from": "engine/site/", "to": "site/", "images": ["quiz-a"],
         "require": [{"file": "site/index.html", "pattern": "<html\\b[^>]*\\sdata-quiz=\"{image}\""}]},
    ]
}


class Sync(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        for img in ("quiz-a", "plain"):
            write(self.root, f"images/{img}/Dockerfile", "FROM x\n")
        write(self.root, "images/not-an-image/readme.txt", "no Dockerfile\n")
        write(self.root, "images/quiz-a/site/index.html", '<html lang="de" data-quiz="quiz-a">\n')
        write(self.root, "images/quiz-a/site/config.js", "own file\n")
        write(self.root, "shared/nginx.conf", "server {}\n")
        write(self.root, "shared/engine/site/main.js", "main\n")
        write(self.root, "shared/engine/site/sub/deep.css", "css\n")
        write(self.root, "shared/engine/site/.DS_Store", "junk\n")
        self.rules(RULES)

    def tearDown(self):
        shutil.rmtree(self.root)

    def rules(self, data):
        write(self.root, "shared/sync.json", json.dumps(data))

    def run_sync(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = sync.run(list(args), self.root)
        return code, out.getvalue()

    def test_sync_then_check(self):
        code, out = self.run_sync("--check")
        self.assertEqual(code, 1)
        self.assertIn("images/quiz-a/site/main.js  (missing", out)
        self.assertIn("sync-manifest.json  (missing)", out)
        self.assertEqual(self.run_sync()[0], 0)
        self.assertEqual(readt(self.root, "images/plain/nginx.conf"), "server {}\n")
        self.assertEqual(readt(self.root, "images/quiz-a/site/sub/deep.css"), "css\n")
        self.assertIsNone(readt(self.root, "images/quiz-a/site/.DS_Store"))
        self.assertIsNone(readt(self.root, "images/not-an-image/nginx.conf"))
        self.assertEqual(readt(self.root, "images/quiz-a/site/config.js"), "own file\n")
        manifest = json.loads(readt(self.root, "shared/sync-manifest.json"))["copies"]
        self.assertEqual(sorted(manifest), ["images/plain/nginx.conf", "images/quiz-a/nginx.conf",
                                            "images/quiz-a/site/main.js", "images/quiz-a/site/sub/deep.css"])
        self.assertEqual(self.run_sync("--check"), (0, "4 copies up to date\n"))

    def test_edited_copy_fails_check_and_sync_restores_it(self):
        self.run_sync()
        write(self.root, "images/quiz-a/site/main.js", "tweaked\n")
        code, out = self.run_sync("--check")
        self.assertEqual(code, 1)
        self.assertIn("images/quiz-a/site/main.js  (differs; source: shared/engine/site/main.js)", out)
        self.assertIn("edit the source under shared/", out)
        self.run_sync()
        self.assertEqual(readt(self.root, "images/quiz-a/site/main.js"), "main\n")

    def test_renamed_source_leaves_a_stale_copy_until_synced(self):
        self.run_sync()
        os.rename(os.path.join(self.root, "shared/engine/site/main.js"), os.path.join(self.root, "shared/engine/site/engine.js"))
        code, out = self.run_sync("--check")
        self.assertEqual(code, 1)
        self.assertIn("images/quiz-a/site/main.js  (stale: a copy of shared/engine/site/main.js", out)
        self.assertIn("images/quiz-a/site/engine.js  (missing", out)
        self.assertIn("sync-manifest.json  (out of date)", out)
        code, out = self.run_sync()
        self.assertEqual(code, 0)
        self.assertIn("removed images/quiz-a/site/main.js", out)
        self.assertIsNone(readt(self.root, "images/quiz-a/site/main.js"))
        self.assertEqual(readt(self.root, "images/quiz-a/site/engine.js"), "main\n")
        self.assertEqual(self.run_sync("--check")[0], 0)

    def test_image_dropped_from_a_rule_loses_its_copies(self):
        self.run_sync()
        data = json.loads(json.dumps(RULES))
        data["rules"] = data["rules"][:1]
        self.rules(data)
        self.assertEqual(self.run_sync("--check")[0], 1)
        self.run_sync()
        self.assertIsNone(readt(self.root, "images/quiz-a/site/main.js"))
        self.assertEqual(readt(self.root, "images/quiz-a/site/index.html"), '<html lang="de" data-quiz="quiz-a">\n')

    def test_edited_former_copy_is_never_deleted(self):
        self.run_sync()
        os.remove(os.path.join(self.root, "shared/engine/site/sub/deep.css"))
        write(self.root, "images/quiz-a/site/sub/deep.css", "now the image's own\n")
        for args in ((), ("--check",)):
            code, out = self.run_sync(*args)
            self.assertEqual(code, 2)
            self.assertIn("images/quiz-a/site/sub/deep.css  (was a copy of shared/engine/site/sub/deep.css)", out)
        self.assertEqual(readt(self.root, "images/quiz-a/site/sub/deep.css"), "now the image's own\n")
        # keeping it: delete its manifest entry
        m = json.loads(readt(self.root, "shared/sync-manifest.json"))
        del m["copies"]["images/quiz-a/site/sub/deep.css"]
        write(self.root, "shared/sync-manifest.json", json.dumps(m))
        self.assertEqual(self.run_sync()[0], 0)
        self.assertEqual(readt(self.root, "images/quiz-a/site/sub/deep.css"), "now the image's own\n")
        self.assertEqual(self.run_sync("--check")[0], 0)

    def test_file_into_a_folder(self):
        data = json.loads(json.dumps(RULES))
        data["rules"][0]["to"] = "conf/"
        self.rules(data)
        self.assertEqual(self.run_sync()[0], 0)
        self.assertEqual(readt(self.root, "images/plain/conf/nginx.conf"), "server {}\n")

    def test_bad_rules_fail_clearly(self):
        os.makedirs(os.path.join(self.root, "images/plain/site"))
        cases = [
            ({"from": "nginx.conf", "to": "site", "images": ["plain"]}, "is a folder; end 'to' with /"),
            ({"from": "engine/site/", "to": "site", "images": ["plain"]}, "'to' must be one too"),
            ({"from": "missing.conf", "to": "x", "images": "*"}, "not found"),
            ({"from": "../images", "to": "x/", "images": "*"}, "inside shared/"),
            ({"from": "nginx.conf", "to": "../escape", "images": ["plain"]}, "inside images/plain/"),
            ({"from": "nginx.conf", "to": "x", "images": ["not-an-image"]}, "not an image folder"),
            ({"from": "nginx.conf", "to": "x", "images": []}, "'images' must be"),
            ({"from": "nginx.conf", "to": "x", "images": "*", "extra": 1}, "keys are"),
            ({"from": "nginx.conf", "to": "/abs", "images": "*"}, "relative path"),
            ({"from": "nginx.conf", "to": "Dockerfile/x", "images": ["plain"]}, "is a file"),
            ({"from": "nginx.conf", "to": "x", "images": "*", "require": [{"file": "a"}]}, "'require' must be"),
        ]
        for rule, msg in cases:
            self.rules({"rules": [rule]})
            for args in ((), ("--check",)):
                code, out = self.run_sync(*args)
                self.assertEqual(code, 2, (rule, out))
                self.assertIn(msg, out, rule)
        self.rules({"rules": [RULES["rules"][0], dict(RULES["rules"][0], to="other")]})
        self.assertEqual(self.run_sync()[0], 0)  # one source, two places: fine
        self.rules({"rules": [RULES["rules"][0], {"from": "engine/site/main.js", "to": "nginx.conf", "images": "*"}]})
        self.assertIn("two sources", self.run_sync()[1])

    def test_require_data_quiz(self):
        for html in ('<html lang="de">\n', '<html lang="de" data-quiz="quiz-b">\n', '<body data-quiz="quiz-a">\n'):
            write(self.root, "images/quiz-a/site/index.html", html)
            for args in ((), ("--check",)):
                code, out = self.run_sync(*args)
                self.assertEqual(code, 2, html)
                self.assertIn("images/quiz-a/site/index.html: must match", out)
        os.remove(os.path.join(self.root, "images/quiz-a/site/index.html"))
        self.assertIn("missing", self.run_sync("--check")[1])


if __name__ == "__main__":
    unittest.main(verbosity=1)
