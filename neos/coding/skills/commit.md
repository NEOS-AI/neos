---
name: commit
description: Create a factual commit only when the user asked.
---

# commit

## When to Use

Use only when the user asked to commit the current workspace change.

## Boundaries

Do not add unrequested files. Do not skip repo hooks.
Do not invent a commit if the user did not ask.

Create a commit only if the user asked. Follow the repo hook policy.
Keep the message factual.
