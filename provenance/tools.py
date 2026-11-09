"""The three provenance tools: remember a fact with its source, recall
what is known with sources attached, and ask where one fact came from.

Schemas follow the shape Hermes expects (copied from the recon plugin's
tool schemas). Handlers never raise: a bad input returns
{"success": false, "error": ...} in plain language.
"""

import json
from datetime import datetime, timezone

from .store import (
    FACT_MAX,
    SOURCE_MAX,
    TOPIC_MAX,
    ProvenanceStore,
)

_STORE = None


def _get_store(ctx=None):
    global _STORE
    if _STORE is None:
        data_dir = None
        if ctx is not None:
            try:
                data_dir = ctx.plugin_data_dir()
            except Exception:
                data_dir = None
        _STORE = ProvenanceStore(data_dir)
    return _STORE


REMEMBER_SCHEMA = {
    "name": "provenance_remember",
    "description": "Store a fact together with where it came from, so the agent can later say how it knows it.",
    "parameters": {
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": "The fact to remember.",
            },
            "source": {
                "type": "string",
                "description": "Where the fact came from: a tool name, a URL, a file, or 'the user said so'.",
            },
            "topic": {
                "type": "string",
                "description": "Optional topic label for the fact.",
            },
        },
        "required": ["fact", "source"],
        "additionalProperties": False,
    },
}

RECALL_SCHEMA = {
    "name": "provenance_recall",
    "description": "Ask what is known about a topic, with each fact's source attached.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look for: a word or phrase from the fact.",
            },
            "limit": {
                "type": "integer",
                "description": "How many matches to return (default 10, max 50).",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

WHERE_FROM_SCHEMA = {
    "name": "provenance_where_from",
    "description": "Ask where one fact came from: the tool, the arguments, and the time.",
    "parameters": {
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": "The fact to trace back to its source.",
            },
        },
        "required": ["fact"],
        "additionalProperties": False,
    },
}


def _need_str(args, key, max_len):
    value = args.get(key) if isinstance(args, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % key)
    if len(value) > max_len:
        raise ValueError("%s is too long (max %d characters)" % (key, max_len))
    return value.strip()


def _limit(args):
    value = args.get("limit", 10) if isinstance(args, dict) else 10
    try:
        value = int(value)
    except Exception:
        return 10
    return max(1, min(value, 50))


def _public(record):
    """The agent-facing shape of one stored record."""
    out = {
        "kind": record.get("kind"),
        "recorded_at": datetime.fromtimestamp(
            record.get("ts", 0), tz=timezone.utc
        ).isoformat(),
    }
    if record.get("kind") == "fact":
        out["fact"] = record.get("fact")
        out["source"] = record.get("source")
        if record.get("topic"):
            out["topic"] = record.get("topic")
    else:
        out["tool"] = record.get("tool")
        out["args"] = record.get("args", {})
        out["status"] = record.get("status")
        out["excerpt"] = record.get("excerpt", "")
    return out


def _ok(tool, **fields):
    out = {"success": True, "tool": tool}
    out.update(fields)
    return json.dumps(out)


def _fail(tool, error):
    return json.dumps({"success": False, "tool": tool, "error": error})


def handle_remember(args, **kwargs):
    try:
        fact = _need_str(args, "fact", FACT_MAX)
        source = _need_str(args, "source", SOURCE_MAX)
        topic = None
        if isinstance(args, dict) and args.get("topic") is not None:
            topic = _need_str(args, "topic", TOPIC_MAX)
        record = _get_store().remember(fact, source, topic)
        return _ok("provenance_remember", stored=_public(record))
    except ValueError as exc:
        return _fail("provenance_remember", str(exc))
    except Exception as exc:
        return _fail("provenance_remember", "could not store the fact (%s)" % exc)


def handle_recall(args, **kwargs):
    try:
        query = _need_str(args, "query", FACT_MAX)
        found = _get_store().search(query, _limit(args))
        return _ok(
            "provenance_recall",
            query=query,
            count=len(found),
            results=[_public(record) for record in found],
        )
    except ValueError as exc:
        return _fail("provenance_recall", str(exc))
    except Exception as exc:
        return _fail("provenance_recall", "could not search the log (%s)" % exc)


def handle_where_from(args, **kwargs):
    try:
        fact = _need_str(args, "fact", FACT_MAX)
        record = _get_store().where_from(fact)
        if record is None:
            return _ok(
                "provenance_where_from",
                fact=fact,
                found=False,
                message="No record of that fact yet.",
            )
        return _ok(
            "provenance_where_from",
            fact=fact,
            found=True,
            source=_public(record),
        )
    except ValueError as exc:
        return _fail("provenance_where_from", str(exc))
    except Exception as exc:
        return _fail(
            "provenance_where_from", "could not trace the fact (%s)" % exc
        )


TOOLS = (
    {
        "name": "provenance_remember",
        "toolset": "provenance",
        "schema": REMEMBER_SCHEMA,
        "handler": handle_remember,
        "description": "Store a fact with its source.",
        "emoji": "📝",
    },
    {
        "name": "provenance_recall",
        "toolset": "provenance",
        "schema": RECALL_SCHEMA,
        "handler": handle_recall,
        "description": "Recall what is known, with sources.",
        "emoji": "🔎",
    },
    {
        "name": "provenance_where_from",
        "toolset": "provenance",
        "schema": WHERE_FROM_SCHEMA,
        "handler": handle_where_from,
        "description": "Trace one fact back to its source.",
        "emoji": "🧭",
    },
)
