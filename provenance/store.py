"""Provenance store: one JSON line per record, in the plugin data dir.

Two kinds of record:
- "tool_result": written automatically by the post_tool_call hook — which
  tool ran, what it was asked (secrets redacted), when, whether it worked,
  and a short excerpt of what came back.
- "fact": written by the provenance_remember tool — a fact and its source,
  as stated by the agent or the user.

The store is plain JSONL, the same pattern the guardrail's audit log uses.
A read failure returns what can be read; a write failure is swallowed —
a store problem must never break the agent loop. The file grows with use;
deleting it starts the log over.
"""

import json
import os
import time

from .redact import redact_text, redact_value

EXCERPT_MAX = 300
FACT_MAX = 1000
SOURCE_MAX = 500
TOPIC_MAX = 200
SEARCH_LIMIT_MAX = 50


class ProvenanceStore:
    def __init__(self, data_dir=None):
        if data_dir:
            base = data_dir
        else:
            base = os.path.join(
                os.path.expanduser("~"),
                ".hermes",
                "plugins",
                "provenance-memory",
            )
        self.path = os.path.join(base, "provenance.jsonl")

    def _append(self, record):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        except Exception:
            pass

    def _read_all(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                out = []
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
                return out
        except Exception:
            return []

    def record_tool_result(self, tool, args, status, excerpt,
                           task_id=None, session_id=None, ts=None):
        """One tool result's provenance. Returns the stored record."""
        record = {
            "ts": ts if ts is not None else time.time(),
            "kind": "tool_result",
            "tool": tool,
            "args": redact_value(args if isinstance(args, dict) else {}),
            "status": status,
            "excerpt": redact_text(excerpt or "")[:EXCERPT_MAX],
        }
        if task_id is not None:
            record["task_id"] = task_id
        if session_id is not None:
            record["session_id"] = session_id
        self._append(record)
        return record

    def remember(self, fact, source, topic=None, ts=None):
        """One fact with its source. Returns the stored record."""
        record = {
            "ts": ts if ts is not None else time.time(),
            "kind": "fact",
            "fact": fact,
            "source": source,
        }
        if topic:
            record["topic"] = topic
        self._append(record)
        return record

    def search(self, query, limit=10):
        """Records whose fact, excerpt, tool name, source, or args contain
        the query (case-insensitive), newest first, capped at 50."""
        try:
            limit = int(limit)
        except Exception:
            limit = 10
        limit = max(1, min(limit, SEARCH_LIMIT_MAX))
        needle = (query or "").lower()
        matches = []
        for record in self._read_all():
            haystack = " ".join(
                str(record.get(key, ""))
                for key in ("fact", "excerpt", "tool", "source", "topic", "args")
            )
            if needle in haystack.lower():
                matches.append(record)
        matches.sort(key=lambda item: item.get("ts", 0), reverse=True)
        return matches[:limit]

    def where_from(self, fact):
        """The most recent record matching fact, or None."""
        found = self.search(fact, limit=1)
        return found[0] if found else None
