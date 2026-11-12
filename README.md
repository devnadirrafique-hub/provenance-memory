# Provenance-memory

Remembers where each piece of information came from, so the agent can say
what it knows and how it knows it.

## Demo

Watch the plugin in action (49 seconds):

[provenance-memory-demo.mp4](demo/provenance-memory-demo.mp4)

## What it does

Two things, both local — nothing leaves the machine, no network, no model
calls, no API keys.

**1. It watches every tool result automatically.** After each tool call,
the plugin writes one line to a local log: which tool ran, what it was
asked, when, whether it worked, and a short excerpt of what came back.
The agent never has to remember to record anything; the provenance is
captured as the work happens.

**2. It gives the agent three tools:**

- `provenance_remember` — store a fact together with its source: a tool
  name, a URL, a file, or "the user said so".
- `provenance_recall` — ask "what do we know about X?" and get the
  matching facts, each with its source attached.
- `provenance_where_from` — ask about one fact and get its source chain:
  the tool, the arguments, and the time.

## How it stores it

One JSON-lines file (`provenance.jsonl`) in the plugin's own data
directory — the same pattern the tool-call guardrail's audit log uses.
Each line is one record: a tool result or a remembered fact. Deleting the
file starts the log over.

Secret-shaped values in tool arguments and in result excerpts are blanked
out before anything is stored (same high-precision patterns as the
tool-call guardrail: known token prefixes, private-key headers, quoted
credential pairs). A secret value is never written to the log.

## What it honestly can't do

- It records where a fact came from, not whether the fact is true.
  Provenance is not truth.
- It stores short excerpts (first 300 characters), not full tool results,
  so the file stays small.
- It only sees what comes through tools. It can't see what the model
  reads on its own.
- The log grows with use. There is no automatic cleanup in version 1 —
  delete the file when you want a fresh start.
- One thing the docs disagree on: the exact field names in the tool-result
  hook. The official docs say `tool_name` and `args`; another source says
  `function_name` and `function_args`. The plugin reads both spellings,
  and the tests cover both.

## How it differs from the catalog's memory plugin

The catalog already has a memory plugin (nexus), but it sends your
queries and memory snippets to an outside service with an API key. This
plugin is the opposite: fully local, and about *sources*, not storage.

## Install

Once this plugin is in the Hermes plugin catalog:

```sh
hermes plugins install devnadirrafique-hub/provenance-memory
```

## Testing

Unit tests (store, redaction, hook, handlers, wiring):

```sh
python -m unittest discover -s tests
```

Hermes's own checks:

```sh
hermes plugins doctor . --ci
hermes plugins validate . --install-deps
```

## License

MIT. Built for the Nous Hermes Agent Plugin Hackathon.

## Credits

Built by Nadir Rafique with Muse, my AI agent — it drafted the code, I tested
and verified every line.
