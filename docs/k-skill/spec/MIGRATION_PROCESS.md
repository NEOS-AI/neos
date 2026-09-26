# k-skill migration process

Code-grounded landing order. Spec is [K_SKILL_NEOS_MIGRATION_SPEC.md](./K_SKILL_NEOS_MIGRATION_SPEC.md) and [02-skills.md](./02-skills.md). Plan: `docs/superpowers/plans/2026-09-26-k-skill-pack.md`.

Work on `dev`. One conventional commit per task. Do not push. TDD: failing test, watch it fail, then implement. pytest via `.venv/bin/pytest`. Local autouse `Settings()` teardown ERROR is pre-existing.

| Step | Deliverable | Commit |
|---|---|---|
| 1 | `k_skill_roots` / `k_skill_catalog` constructors + isolation tests (empty pack still allowed; names empty until vendor) | `test(k-skill): pin catalog constructors` then `feat(skills): add k_skill_catalog` |
| 2 | Vendor 125 skill directories from `../k-skill` with composed SKILL.md | `feat(k-skill): vendor 125 markdown skills` |
| 3 | Pack tests: count 125, exclusions, body is instruction not CLI stub | `test(k-skill): pin vendored pack` |
| 4 | Coding index skill `neos/coding/skills/k-skill.md` | `feat(coding): add k-skill index skill` |
| 5 | Coding `load_skill.v1` fallback to `k_skill_catalog()` | `feat(coding): load k-skill pack names` |

Do not land HTTP, UI, ParentKind, or proxy code in this sequence.
