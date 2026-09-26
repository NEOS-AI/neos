# 02. security-audit pack + catalog + coding fallback

이 장은 **구현 계약**이다. [00-overview.md](../00-overview.md)는 원본 인벤토리고, 이 파일이 팩 착륙의 정본이다.

## 1. Target layout

```
skills/security-audit/
  LICENSE
  SOURCE.md
  security-audit/
    SKILL.md
    RECONNAISSANCE.md
    HUNTING.md
    VALIDATION-AND-REPORTING.md
    ATTACK-CLASSES.md
    <10 domain companions>
    report-schema.json
    validate-findings.cjs
    validate-coverage-ledger.cjs
    validate-*.test.cjs
    references/                 # copies of the 14 companion .md files
neos/coding/skills/security-audit.md
```

On-disk directory name = YAML `name` = catalog lookup key = `security-audit`.

`load_markdown(..., reference=leaf)` resolves `references/<leaf>.md`. Validators are not catalog names; the body tells the agent to run `node …/validate-findings.cjs`.

## 2. Catalog constructors

File: `neos/skills/markdown_catalog.py`.

```python
SECURITY_AUDIT_PACK = _REPO_ROOT / "skills" / "security-audit"


def security_audit_roots() -> tuple[tuple[SkillSource, Path], ...]:
    """Immediate-child SKILL.md scan under skills/security-audit."""
    return (("repo", SECURITY_AUDIT_PACK),)


def security_audit_catalog() -> MarkdownSkillCatalog:
    return MarkdownSkillCatalog(roots=security_audit_roots())
```

Do not add a new `SkillSource`. Do not recurse. Do not put `SECURITY_AUDIT_PACK` on `default_skill_roots()` or `research_skill_roots()`. Do not merge into other pack catalogs. `skip_names` is empty.

## 3. Vendor

`scripts/vendor_security_audit.py` copies `../security-audit-skill/skills/security-audit/` into the nested child, copies companion `.md` into `references/`, copies pack-root `LICENSE` from the clone root, writes `SOURCE.md` with sibling `../security-audit-skill` plus `git rev-parse HEAD`. Never write `/Users/…`.

Do not compose from `skill.json`. Upstream `SKILL.md` is the body.

## 4. Coding index

`neos/coding/skills/security-audit.md` has exact ATX `## When to Use` / `## Boundaries`. Prompt lists `- security-audit:` and does not list `- HUNTING:` or `- RECONNAISSANCE:`.

## 5. load_skill.v1

Order: `default_catalog()` → `k_skill_catalog()` → `security_audit_catalog()`.

Same-name exception: default hit on coding index `security-audit` prefers the pack catalog for body and `reference=`.

Still deny `pdf`, `xlsx-author`, `univer-sheets-headless`, `k-skill-setup`, `k-skill-cleaner`, and companion filenames used as `name=`.

## 6. Subagent specs

RO tool set (explore minus spawn and DA search/fetch):

`read_file.v1`, `search_text.v1`, `glob_files.v1`, `list_tree.v1`, `stat.v1`, `git_status.v1`, `git_diff.v1`, `git_log.v1`.

Both specs: `SandboxMode.PARENT_RO`, `can_spawn=False`, `one_shot=True`, `can_approve=False`, `load_project_instructions=False`.
