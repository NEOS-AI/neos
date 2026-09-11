---
name: verify
description: Run tests and report a structured verdict.
---

# verify

## When to Use

Use after implementation when you need to check that the change works.

## Boundaries

Do not edit or write project files in this phase. Do not spawn agents.
Do not claim success if you did not run the checks.

Run the project's tests and linters when they exist. Do not skip hooks.

For each check:

- Command: the exact argv you ran
- Output: the relevant tail
- Result: pass or fail

End with `VERDICT: PASS`, `VERDICT: FAIL`, or `VERDICT: PARTIAL`.
