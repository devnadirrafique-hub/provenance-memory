"""Unit tests for the provenance store, the redaction, and the three
tool handlers. No Hermes install and no network needed: everything runs
against a temporary data directory.

Run from the plugin directory with: python -m unittest discover -s tests
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from provenance import tools as tools_mod
from provenance.redact import redact_text, redact_value
from provenance.store import ProvenanceStore


class StoreTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ProvenanceStore(self.tmp.name)
        # Point the tool handlers at this store, not the real data dir.
        tools_mod._STORE = self.store

    def tearDown(self):
        tools_mod._STORE = None
        self.tmp.cleanup()


class TestStore(StoreTestBase):
    def test_remember_stores_fact_and_source(self):
        record = self.store.remember(
            "The API lives at api.example.com", "from the docs", ts=1000.0
        )
        self.assertEqual(record["kind"], "fact")
        self.assertEqual(record["fact"], "The API lives at api.example.com")
        self.assertEqual(record["source"], "from the docs")
        found = self.store.search("api.example.com")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["fact"], "The API lives at api.example.com")

    def test_record_tool_result_stores_tool_args_status_excerpt(self):
        record = self.store.record_tool_result(
            tool="recon_subdomains",
            args={"domain": "example.com"},
            status="ok",
            excerpt='{"subdomains": ["www.example.com"]}',
            task_id="t1",
            ts=2000.0,
        )
        self.assertEqual(record["tool"], "recon_subdomains")
        self.assertEqual(record["args"], {"domain": "example.com"})
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["task_id"], "t1")

    def test_excerpt_capped_at_300_chars(self):
        record = self.store.record_tool_result(
            tool="t", args={}, status="ok", excerpt="x" * 500, ts=1.0
        )
        self.assertEqual(len(record["excerpt"]), 300)

    def test_search_is_case_insensitive(self):
        self.store.remember("The API lives at api.example.com", "docs", ts=1.0)
        self.assertEqual(len(self.store.search("API.EXAMPLE")), 1)

    def test_search_matches_tool_name(self):
        self.store.record_tool_result(
            tool="recon_wayback_urls", args={}, status="ok",
            excerpt="http://example.com/", ts=1.0,
        )
        self.assertEqual(len(self.store.search("wayback")), 1)

    def test_search_newest_first(self):
        self.store.remember("first fact", "s1", ts=100.0)
        self.store.remember("second fact", "s2", ts=200.0)
        found = self.store.search("fact")
        self.assertEqual(found[0]["fact"], "second fact")
        self.assertEqual(found[1]["fact"], "first fact")

    def test_search_limit_clamps_to_50(self):
        for i in range(60):
            self.store.remember("fact %d" % i, "s", ts=float(i))
        self.assertEqual(len(self.store.search("fact", limit=100)), 50)
        self.assertEqual(len(self.store.search("fact", limit=0)), 1)

    def test_where_from_returns_most_recent_match(self):
        self.store.remember("the token is dead", "old notes", ts=100.0)
        self.store.remember("the token is dead", "new notes", ts=200.0)
        found = self.store.where_from("token is dead")
        self.assertEqual(found["source"], "new notes")

    def test_where_from_returns_none_when_absent(self):
        self.assertIsNone(self.store.where_from("nothing like this"))

    def test_missing_file_searches_empty(self):
        empty = ProvenanceStore(os.path.join(self.tmp.name, "no-such-dir"))
        self.assertEqual(empty.search("anything"), [])

    def test_secret_in_args_is_redacted_before_storing(self):
        record = self.store.record_tool_result(
            tool="t",
            args={"token": "sk-abcdefghij1234567890"},
            status="ok",
            excerpt="",
            ts=1.0,
        )
        self.assertEqual(record["args"], {"token": "[redacted]"})

    def test_secret_in_excerpt_is_redacted_before_storing(self):
        record = self.store.record_tool_result(
            tool="t",
            args={},
            status="ok",
            excerpt="result: ghp_" + "a" * 36,
            ts=1.0,
        )
        self.assertNotIn("ghp_", record["excerpt"])
        self.assertIn("[redacted]", record["excerpt"])


class TestRedact(unittest.TestCase):
    def test_api_key_prefix_redacted(self):
        self.assertEqual(
            redact_text("key is sk-abcdefghij1234567890 done"),
            "key is [redacted] done",
        )

    def test_github_pat_redacted(self):
        # A real classic PAT is ghp_ + 36 characters.
        self.assertEqual(redact_text("ghp_" + "b" * 36), "[redacted]")

    def test_aws_key_redacted(self):
        self.assertEqual(redact_text("AKIA" + "C" * 16), "[redacted]")

    def test_private_key_header_redacted(self):
        self.assertEqual(
            redact_text("-----BEGIN RSA PRIVATE KEY-----"), "[redacted]"
        )

    def test_quoted_credential_pair_redacted(self):
        # Unquoted key with a quoted value, as in a command line or a
        # config line. (A JSON-style "api_key": "value" keeps its key
        # quotes, so this pattern does not fire on it — the value itself
        # is what gets redacted there, via the prefix patterns.)
        self.assertEqual(
            redact_text('api_key="hunter2hunter2"'), "[redacted]"
        )

    def test_ordinary_text_untouched(self):
        text = "domain: example.com, count 5, status ok"
        self.assertEqual(redact_text(text), text)

    def test_nested_values_redacted(self):
        value = {"a": ["sk-abcdefghij1234567890"], "b": {"c": "plain"}}
        self.assertEqual(
            redact_value(value),
            {"a": ["[redacted]"], "b": {"c": "plain"}},
        )

    def test_non_strings_pass_through(self):
        self.assertEqual(redact_value(42), 42)
        self.assertIsNone(redact_value(None))


class TestHandlers(StoreTestBase):
    def _call(self, handler, args):
        return json.loads(handler(args))

    def test_remember_returns_stored_fact_with_source(self):
        out = self._call(
            tools_mod.handle_remember,
            {"fact": "The API lives at api.example.com", "source": "from the docs"},
        )
        self.assertTrue(out["success"])
        self.assertEqual(out["stored"]["fact"], "The API lives at api.example.com")
        self.assertEqual(out["stored"]["source"], "from the docs")
        self.assertIn("recorded_at", out["stored"])

    def test_remember_rejects_empty_fact(self):
        out = self._call(tools_mod.handle_remember, {"fact": "  ", "source": "x"})
        self.assertFalse(out["success"])
        self.assertIn("fact", out["error"])

    def test_remember_rejects_too_long_fact(self):
        out = self._call(
            tools_mod.handle_remember, {"fact": "x" * 1001, "source": "s"}
        )
        self.assertFalse(out["success"])

    def test_recall_returns_facts_with_sources(self):
        self.store.remember("The API lives at api.example.com", "from the docs", ts=1.0)
        self.store.remember("The API key is rotated weekly", "the user said so", ts=2.0)
        out = self._call(tools_mod.handle_recall, {"query": "API"})
        self.assertTrue(out["success"])
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["results"][0]["source"], "the user said so")
        self.assertEqual(out["results"][1]["source"], "from the docs")

    def test_recall_no_match_returns_empty(self):
        out = self._call(tools_mod.handle_recall, {"query": "nothing here"})
        self.assertTrue(out["success"])
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["results"], [])

    def test_recall_rejects_empty_query(self):
        out = self._call(tools_mod.handle_recall, {"query": ""})
        self.assertFalse(out["success"])

    def test_where_from_found_returns_source_chain(self):
        self.store.record_tool_result(
            tool="recon_subdomains",
            args={"domain": "example.com"},
            status="ok",
            excerpt="www.example.com",
            ts=500.0,
        )
        out = self._call(
            tools_mod.handle_where_from, {"fact": "www.example.com"}
        )
        self.assertTrue(out["success"])
        self.assertTrue(out["found"])
        self.assertEqual(out["source"]["tool"], "recon_subdomains")
        self.assertEqual(out["source"]["args"], {"domain": "example.com"})

    def test_where_from_not_found_says_so(self):
        out = self._call(tools_mod.handle_where_from, {"fact": "no such fact"})
        self.assertTrue(out["success"])
        self.assertFalse(out["found"])
        self.assertIn("No record", out["message"])

    def test_handlers_never_raise_on_bad_input(self):
        for handler in (
            tools_mod.handle_remember,
            tools_mod.handle_recall,
            tools_mod.handle_where_from,
        ):
            for bad in (None, "not a dict", 42, {}):
                out = json.loads(handler(bad))
                self.assertFalse(out["success"])
                self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
