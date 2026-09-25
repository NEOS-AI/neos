---
name: univer-docs-headless
description: Headless Univer Docs via structured univer.*.v1 tools on the Python InMemorySidecar. Use univer.execute_command.v1 with doc.command.insert-text {text} splice on IDocumentData-shaped JSON. Do not hand-edit dataStream. Not for DOCX exchange, Slides, or Pro collaboration.
---

# Univer Docs (headless)

## Runtime

Live engine is Python `InMemorySidecar`. Node `@univerjs` presets are deferred. Parent owns the sidecar.

Call structured tools:

- `univer.inspect.v1` — title, dataStream length, paragraphs
- `univer.execute_command.v1` — allowlisted doc COMMANDs
- `univer.save.v1` — write `draft/document.json` only

Sheet tools (`range_get` / `range_set`) do not apply to a doc unit.

## Write

Live insert path is `doc.command.insert-text` with params `{text}`. The sidecar splices `text` in front of the trailing paragraph/section terminator. Empty body is `\r\n`. After insert `"Hello"`, the stream is `"Hello\r\n"`.

`doc.command.update-text` with `{text}` replaces the whole body with `text + "\r\n"`.

Do not hand-edit `body` or `dataStream`. Offsets and paragraph ids are not a live OT API this wave.

Sheet COMMANDs on a doc unit return `unit_kind_mismatch`. MUTATION ids are `mutation_forbidden`.

## Save

`univer.save.v1` writes `draft/document.json`. Snapshot is a subset (`id`, `title`, `appVersion`, `body.dataStream`, placeholder `documentStyle` / `paragraphs`). It is not a round-trip `IDocumentData`.

## Forbidden

DOCX round-trip (Pro), Slides, header/footer `dataStream` patches, and merging trunk.
