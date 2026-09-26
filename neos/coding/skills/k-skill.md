---
name: k-skill
description: Korean public-data and daily-life skill pack. Load a pack name with load_skill.v1.
---

# k-skill

## When to Use

Use when the user asks about Korean public data or daily-life tasks that a pack skill covers: weather, transit, real estate, law, taxes, shopping, sports, holidays, HWP, or similar.

Call `load_skill.v1` with the pack directory name (`korea-weather`, `korean-law-search`, `railway-timetable`, …). Do not invent names. Do not load `k-skill-setup` or `k-skill-cleaner`.

## Boundaries

Do not paste all 125 descriptions into the prompt. Do not execute payment, message delivery, final submission, or cancellation without the user's explicit approval immediately beforehand. Do not ask for or print plaintext credentials. Pack bodies live under `skills/k-skill/<name>/SKILL.md`.
