---
name: univer-formula-audit
description: Audit Univer formula-engine results. Use to wait on dirty calculation, list ErrorType literals, and read getFormulaError/getAllFormulaError. Never register custom RPC functions. Not for writing cells to disk.
---

# Univer formula audit

A formula leaf that loads this skill has no `write_file.v1`. Engine mutations apply only in sidecar memory through `univer.formula_wait.v1`.

## ErrorType

Twelve literals from `engine-formula` `basics/error-type.ts`. List them all:

`#DIV/0!` `#NAME?` `#VALUE!` `#NUM!` `#N/A` `#CYCLE!` `#REF!` `#SPILL!` `#CALC!` `#ERROR!` `#GETTING_DATA` `#NULL!`

`#CYCLE!` is defined but is not applied automatically to every cyclic graph. `#NULL!` is for space-intersection comments. Do not teach that every cycle is `#CYCLE!`.

## Dirty

`ActiveDirtyController` watches sheet mutations. **Style-only** `SetRangeValues` is skipped. The trigger is a 10ms debounce. Results land on cell `v` / `t` via `SetRangeValuesMutation`.

## Wait

`onCalculationResultApplied(timeout?)`. If the model was touched from outside, call `executeCalculation()`. `getValue()` before wait finishes may be stale.

## Error lookup

`FRange.getFormulaError()`, `FWorkbook.getAllFormulaError()`.

## Custom functions

`sheets-formula.remote-register-function.service` deserialization throws (`unsafe`). Facade `registerFunction` is main-thread only. **v0 does not register custom functions.** Do not send function source over RPC.

## Disk

This skill does not write cells to disk. Sidecar `univer.formula_wait.v1` applies engine mutation in memory only.
