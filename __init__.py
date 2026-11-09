"""Provenance-memory plugin for Hermes Agent.

Registers one hook and three tools (see provenance/):
- post_tool_call: captures the provenance of every tool result
  automatically — which tool, what it was asked, when, whether it worked.
- provenance_remember: store a fact together with its source.
- provenance_recall: ask what is known about a topic, sources attached.
- provenance_where_from: trace one fact back to its source.

The store and the hook live in provenance/ and have no Hermes dependency,
so they can be unit-tested without Hermes installed. This file is only the
wiring between Hermes and the engine.
"""

from .provenance import hooks, tools


def register(ctx):
    hooks._get_store(ctx)
    tools._get_store(ctx)
    ctx.register_hook("post_tool_call", hooks.post_tool_call)
    for tool in tools.TOOLS:
        ctx.register_tool(
            name=tool["name"],
            toolset=tool["toolset"],
            schema=tool["schema"],
            handler=tool["handler"],
            description=tool["description"],
            emoji=tool["emoji"],
        )
