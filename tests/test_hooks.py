"""Hook and wiring tests: does the post_tool_call hook capture provenance
under both payload spellings, and does the plugin register exactly the
three tools and the one hook with Hermes?

Run from the plugin directory with: python -m unittest discover -s tests -v
Uses a fake ctx object that mimics what Hermes hands to register().
No network is touched.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from provenance import hooks as hooks_mod
from provenance.store import ProvenanceStore


class FakeCtx:
    """Stands in for the ctx object Hermes passes to register()."""

    def __init__(self, data_dir=None):
        self.tools = {}
        self.hooks = {}
        self._data_dir = data_dir

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = {
            "toolset": toolset,
            "schema": schema,
            "handler": handler,
            "kwargs": kwargs,
        }

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def plugin_data_dir(self):
        return self._data_dir


def load_plugin_root():
    # Mirror how Hermes loads a directory plugin: __init__.py is imported
    # as a package with __package__ set and the plugin directory as its
    # search path, so the relative imports in __init__.py resolve.
    # Clear any earlier load first: the provenance modules hold a
    # module-level store singleton, and a stale load would keep pointing
    # at the previous test's (deleted) data directory.
    for key in [k for k in sys.modules if k == "plugin_root" or k.startswith("plugin_root.")]:
        del sys.modules[key]
    plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(plugin_dir, "__init__.py")
    spec = importlib.util.spec_from_file_location(
        "plugin_root", path, submodule_search_locations=[plugin_dir]
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "plugin_root"
    sys.modules["plugin_root"] = module
    spec.loader.exec_module(module)
    return module


class HookTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        hooks_mod._STORE = ProvenanceStore(self.tmp.name)

    def tearDown(self):
        hooks_mod._STORE = None
        self.tmp.cleanup()


class TestHook(HookTestBase):
    def test_records_tool_result_official_spelling(self):
        hooks_mod.post_tool_call(
            tool_name="recon_subdomains",
            args={"domain": "example.com"},
            result='{"count": 5}',
            task_id="t1",
            duration_ms=120,
            status="ok",
        )
        store = ProvenanceStore(self.tmp.name)
        found = store.search("recon_subdomains")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["args"], {"domain": "example.com"})
        self.assertEqual(found[0]["status"], "ok")
        self.assertIn("count", found[0]["excerpt"])

    def test_records_tool_result_alternate_spelling(self):
        # One third-party source says the payload uses function_name /
        # function_args. The hook must work with that spelling too.
        hooks_mod.post_tool_call(
            function_name="recon_wayback_urls",
            function_args={"domain": "example.com"},
            result="http://example.com/",
            task_id="t2",
            duration_ms=90,
            status="ok",
        )
        store = ProvenanceStore(self.tmp.name)
        found = store.search("wayback")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["tool"], "recon_wayback_urls")

    def test_hook_redacts_secret_in_args(self):
        hooks_mod.post_tool_call(
            tool_name="terminal",
            args={"command": "curl -H 'Authorization: Bearer sk-abcdefghij1234567890' x"},
            result="ok",
            task_id="t3",
            duration_ms=10,
            status="ok",
        )
        store = ProvenanceStore(self.tmp.name)
        found = store.search("terminal")
        self.assertNotIn("sk-", json.dumps(found[0]["args"]))
        self.assertIn("[redacted]", json.dumps(found[0]["args"]))

    def test_hook_never_raises_when_result_cannot_be_stringified(self):
        class BadResult:
            def __str__(self):
                raise RuntimeError("no string for you")

        hooks_mod.post_tool_call(
            tool_name="t", args={}, result=BadResult(),
            task_id="t4", duration_ms=1, status="ok",
        )
        store = ProvenanceStore(self.tmp.name)
        found = store.search("t")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["excerpt"], "")

    def test_hook_never_raises_when_store_is_unusable(self):
        # A data dir that is actually a file: every write fails silently.
        bad = os.path.join(self.tmp.name, "not-a-dir")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("x")
        hooks_mod._STORE = ProvenanceStore(bad)
        hooks_mod.post_tool_call(
            tool_name="t", args={}, result="ok",
            task_id="t5", duration_ms=1, status="ok",
        )  # must not raise


class TestWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plugin = load_plugin_root()
        self.ctx = FakeCtx(data_dir=self.tmp.name)
        self.plugin.register(self.ctx)

    def tearDown(self):
        self.tmp.cleanup()

    def test_registers_exactly_the_three_tools(self):
        self.assertEqual(
            set(self.ctx.tools.keys()),
            {
                "provenance_remember",
                "provenance_recall",
                "provenance_where_from",
            },
        )

    def test_tools_share_the_provenance_toolset(self):
        for name, tool in self.ctx.tools.items():
            self.assertEqual(tool["toolset"], "provenance", name)

    def test_registers_exactly_the_one_hook(self):
        self.assertEqual(set(self.ctx.hooks.keys()), {"post_tool_call"})

    def test_store_file_lands_in_the_plugin_data_dir(self):
        handler = self.ctx.tools["provenance_remember"]["handler"]
        out = json.loads(
            handler({"fact": "x", "source": "y"})
        )
        self.assertTrue(out["success"])
        self.assertTrue(
            os.path.exists(os.path.join(self.tmp.name, "provenance.jsonl"))
        )

    def test_hook_and_tool_share_the_same_log(self):
        self.ctx.hooks["post_tool_call"](
            tool_name="recon_subdomains",
            args={"domain": "example.com"},
            result="www.example.com",
            task_id="t",
            duration_ms=5,
            status="ok",
        )
        handler = self.ctx.tools["provenance_where_from"]["handler"]
        out = json.loads(handler({"fact": "www.example.com"}))
        self.assertTrue(out["found"])
        self.assertEqual(out["source"]["tool"], "recon_subdomains")


if __name__ == "__main__":
    unittest.main()
