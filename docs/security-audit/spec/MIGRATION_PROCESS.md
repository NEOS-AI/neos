# security-audit migration process

Code-grounded landing order. Spec is [SECURITY_AUDIT_NEOS_MIGRATION_SPEC.md](./SECURITY_AUDIT_NEOS_MIGRATION_SPEC.md) and [02-skills.md](./02-skills.md). Plan: `docs/superpowers/plans/2026-09-26-security-audit-pack.md`.

Work on `dev`. One conventional commit per task. Do not push. TDD: failing test, watch it fail, then implement. pytest via `.venv/bin/pytest`. Local autouse `Settings()` teardown ERROR is pre-existing.

| Step | Deliverable | Commit |
|---|---|---|
| 1 | `security_audit_roots` / `security_audit_catalog` + isolation tests | `test(security-audit): pin catalog constructors` then `feat(skills): add security_audit_catalog` |
| 2 | Vendor one skill directory from `../security-audit-skill` | `feat(security-audit): vendor markdown skill pack` |
| 3 | Pack tests: count 1, references/, SOURCE.md sibling pin | `test(security-audit): pin vendored pack` |
| 4 | Coding index skill `neos/coding/skills/security-audit.md` | `feat(coding): add security-audit index skill` |
| 5 | Coding `load_skill.v1` pack prefer + k-skill still first | `feat(coding): load security-audit pack body` |
| 6 | Two kebab specs + metrics + stepper prompt | `feat(subagent): add security-audit leaves` |
| 7 | Coding spawn allows the two kebabs | `feat(coding): spawn security-audit specs` |

Do not land HTTP, UI, ParentKind, child execute, or validator Python ports in this sequence.
