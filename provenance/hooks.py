"""post_tool_call hook: capture the provenance of every tool result.

The official docs say the payload carries tool_name and args; one
third-party source claims function_name and function_args instead. This
hook reads both spellings so it works either way. It never raises: a
provenance failure must never break the agent loop. The return value is
ignored by Hermes (post_tool_call is audit-only).
"""

from .store import ProvenanceStore

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


def post_tool_call(tool_name=None, args=None, result=None, task_id=None,
                   duration_ms=None, **kwargs):
    """Record one tool result's provenance."""
    try:
        name = tool_name or kwargs.get("function_name") or "unknown"
        call_args = args
        if not isinstance(call_args, dict):
            call_args = kwargs.get("function_args")
            if not isinstance(call_args, dict):
                call_args = {}
        status = kwargs.get("status", "ok")
        try:
            excerpt = "" if result is None else str(result)
        except Exception:
            excerpt = ""
        _get_store().record_tool_result(
            tool=name,
            args=call_args,
            status=status,
            excerpt=excerpt,
            task_id=task_id,
            session_id=kwargs.get("session_id"),
        )
    except Exception:
        pass
    return None
