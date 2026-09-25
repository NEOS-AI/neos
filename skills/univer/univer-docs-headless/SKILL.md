---
name: univer-docs-headless
description: Headless Univer Docs via FDocument.insertText and save(). Use for plain-text edits on IDocumentData JSON snapshots. Do not hand-edit dataStream or OT. Not for DOCX exchange, Slides, or Pro collaboration.
---

# Univer Docs (headless)

## Boot

Use `preset-docs-node-core`. `univerAPI.createDocument(data)` returns `FDocument`.

## Write

`FDocument.insertText(index, text, segmentId?)`. Paragraphs go through `insertParagraph` / `appendParagraph`. The canonical mutation is `doc.mutation.rich-text-editing` (JSONX/TextX).

## Save

`FDocument.save()` returns `IDocumentData` plus plugin resources.

## dataStream

The implementation enum is canonical (`DataStreamTreeTokenType`):

| Token | Value |
| --- | --- |
| PARAGRAPH | `\r` |
| SECTION_BREAK | `\n` |
| TABLE | `\x1A` … `\x0F` |
| custom range START / END | `\x1F` / `\x1E` |

`IDocumentBody` JSDoc that marks table ends as `\x1E` / `\x1F` is **stale** — those codes are custom range.

## OT

Do not hand-edit `body` or `dataStream`. `paragraphId` and JSONX invert break. An empty body is `dataStream: '\r\n'`.

## Lookup

`getParagraphs` / `findParagraphByText`. `FDocumentTextRange.describe()` is the agent-facing serializable summary. Offsets are frozen at creation — if you edit before a range, recapture it.

## Forbidden

DOCX round-trip (Pro), Slides (`createSlide` / Facade do not exist), and patching headers or footers by writing `dataStream` directly.
