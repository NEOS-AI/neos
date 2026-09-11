---
name: plan
description: Write a read-only implementation plan with critical files.
---

# plan

## When to Use

Use before implementation when the change needs a short design and a file list.

## Boundaries

Do not edit or write project files in this phase. Do not execute commands.
Do not spawn agents. Do not switch to implement until the plan lists critical
files and the user accepts it.

## Critical Files

List 3–5 workspace paths the change will touch, under a `Critical Files:` heading.
