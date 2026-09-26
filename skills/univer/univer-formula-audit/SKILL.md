---
name: univer-formula-audit
description: Audit Univer formula-engine results on the Python InMemorySidecar. Use univer.formula_wait.v1 then inspect. SUM, IF, and arithmetic compute; other functions are #NAME?. Never register custom RPC functions. Not for writing cells to disk.
---

# Univer formula audit

A formula leaf that loads this skill has no `write_file.v1`. Engine mutations apply only in sidecar memory through `univer.formula_wait.v1`. Live runtime is Python `InMemorySidecar`. Node `@univerjs` formula worker is deferred.

## Supported this wave

`SUM`, `IF`, and arithmetic (`+ - * /`, comparisons, A1 and ranges). Other function names evaluate to `#NAME?`. Division by zero is `#DIV/0!`. Lowercase `if` is `#NAME?`.

## ErrorType

Twelve literals from `engine-formula` `basics/error-type.ts`. List them all:

`#DIV/0!` `#NAME?` `#VALUE!` `#NUM!` `#N/A` `#CYCLE!` `#REF!` `#SPILL!` `#CALC!` `#ERROR!` `#GETTING_DATA` `#NULL!`

`#CYCLE!` is defined but is not applied automatically to every cyclic graph. `#NULL!` is for space-intersection comments. Do not teach that every cycle is `#CYCLE!`.

## Wait

Call `univer.formula_wait.v1` after dirty writes. Response is `{ok, formula_dirty}` or `formula_timeout` / `unit_busy`. `wait_status` / `error_count` belong to the formula fold schema, not the tool payload.

Inspect with `univer.inspect.v1` (`include_formula_errors`) and `univer.range_get.v1` after wait. Values read before wait may be stale; inspect-with-values while dirty is `formula_dirty`.

Style-only range writes do not dirty formulas.

## Custom functions

v0 does not register custom functions. Do not send function source over RPC.

## Disk

This skill does not write cells to disk. Sidecar `univer.formula_wait.v1` applies engine mutation in memory only.
