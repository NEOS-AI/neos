# 02. k-skill pack + catalog + coding fallback

이 장은 **구현 계약**이다. [00-overview.md](../00-overview.md)는 원본 인벤토리고, 이 파일이 팩 착륙의 정본이다.

## 1. Target layout

```
skills/k-skill/
  LICENSE
  SOURCE.md                         # sibling path + pin note
  <skill>/
    SKILL.md                        # composed: skill.json frontmatter + instruction.md
    skill.json                      # provenance
    instruction.md                  # provenance
    scripts/                        # if present in source
    references/                     # if present
    templates/                      # if present (HWP fill maps)
    tests/                          # if present
    LICENSE.upstream                # if present
    NOTICE                          # if present
neos/coding/skills/k-skill.md       # coding index skill
```

On-disk directory name = YAML `name` = catalog lookup key. No mismatches in the source (all 127 `skill.json.name` equal the directory). Keep it that way.

`load_markdown(..., reference=leaf)` already resolves `references/<leaf>.md` then `reference/`. Scripts are not loaded by the catalog; the body tells the agent how to run them.

## 2. Catalog constructors

File: `neos/skills/markdown_catalog.py`.

```python
K_SKILL_PACK = _REPO_ROOT / "skills" / "k-skill"

K_SKILL_EXCLUDED: frozenset[str] = frozenset({"k-skill-setup", "k-skill-cleaner"})


def k_skill_roots() -> tuple[tuple[SkillSource, Path], ...]:
    """Immediate-child SKILL.md scan under skills/k-skill."""
    return (("repo", K_SKILL_PACK),)


def k_skill_catalog() -> MarkdownSkillCatalog:
    return MarkdownSkillCatalog(roots=k_skill_roots())
```

Do not add a new `SkillSource`. Do not recurse. Do not put `K_SKILL_PACK` on `default_skill_roots()` or `research_skill_roots()`.

`k_skill-setup` / `k-skill-cleaner` must not exist as child directories, so the scanner cannot index them.

## 3. Composed SKILL.md

Vendor script writes:

```markdown
---
<skill.json.frontmatter, trimmed>
---

<instruction.md, stripped of a leading YAML fence if any>
```

Do not emit the generated CLI stub (`npx ... instruct`). The coding agent already has `load_skill.v1`; it does not need a second installer.

If `instruction.md` contains `npx -y @nomadamas/k-skill@0 exec ...`, leave it. Helpers that exist under `scripts/` can be run that way or as `python skills/k-skill/<name>/scripts/...`. Do not rewrite every helper path in v0.

## 4. Port set (125)

Alphabetical. Tests pin this frozenset.

```
animal-pharmacy-search
assembly-bill-vote-search
bccard-eatpl-search
biz-health-check
bok-ecos-stats
building-register-search
bunjang-search
cheap-gas-nearby
consumer-price-safety-search
corporate-registration-consulting
coupang-product-search
court-auction-notice-search
court-payment-order-assistant
d2b-notice-search
daangn-cars-search
daangn-jobs-search
daangn-realty-search
daangn-used-goods-search
daishin-report-search
daiso-product-search
danawa-price-search
delivery-tracking
donation-place-search
emergency-room-beds
ev-charger-nearby
ev-subsidy-status
express-bus-booking
fine-dust-location
flight-ticket-search
foresttrip-vacancy
fsc-corporate-info
g2b-order-plan-search
g2b-sanctioned-supplier
geeknews-search
gongsijiga-search
gov-overseas-trip-report
government-support-survey
han-river-water-level
hankookilbo-news
highway-traffic-status
hola-poke-yeoksam
household-waste-info
housing-official-price
hwp
intercity-bus-booking
iros-registry-automation
job-posting-match
jobkorea-talent-search
joseon-sillok-search
k-dart
k-schoollunch-menu
kakao-bar-nearby
kakao-map
kakaotalk-mac
kamis-food-price
kbl-results
kbo-results
keris-academic-search
kleague-results
komsa-ferry-info
kopis-performance-search
korea-weather
korean-character-count
korean-cinema-search
korean-heritage-search
korean-holiday-calendar
korean-humanizer
korean-jangbu-for
korean-law-search
korean-marathon-schedule
korean-middle-korean
korean-patent-search
korean-privacy-terms
korean-scholarship-search
korean-slang-writing
korean-spell-check
korean-stock-search
korean-transit-route
kosis-stats
kr-whois-lookup
kstartup-search
lck-analytics
lh-notice-search
library-book-search
localdata-business-status
lotto-results
market-kurly-search
mfds-drug-safety
mfds-food-safety
mofa-travel-safety
multi-asset-morning-briefing
myrealtrip-search
naming-house
national-pension-workplace
naver-ad-performance
naver-blog-research
naver-news-search
naver-shopping-search
nhis-care-checkup-search
nts-business-registration
nts-tax-delinquency
ohou-today-deal
olive-young-search
parking-lot-search
popbill
public-restroom-nearby
railway-timetable
real-estate-search
religious-facility-search
rhwp-advanced
rhwp-edit
s2b-notice-search
saju-fortune
saramin-talent-search
seoul-bike
seoul-density
seoul-subway-arrival
seoul-weather-risk
sh-notice-search
sharenuri-facility-search
store-longevity-radar
subway-lost-property
ticket-availability
toss-investment
zipcode-search
```

Not in the set: `k-skill-setup`, `k-skill-cleaner`, `xlsx-author`, `univer-sheets-headless`, `pdf`.

## 5. Coding index skill

File: `neos/coding/skills/k-skill.md`.

Must pass `_coding_sections_valid` (exact `## When to Use` and `## Boundaries` with non-empty bodies).

Frontmatter:

```yaml
name: k-skill
description: Korean public-data and daily-life skill pack. Load a pack name with load_skill.v1.
```

Body must tell the agent:

- Pack lives in `skills/k-skill/<name>/`.
- Call `load_skill.v1` with the directory name (`korea-weather`, `korean-law-search`, …).
- Do not invent names. Do not load `k-skill-setup` or `k-skill-cleaner`.
- Payment, message delivery, final submission, cancellation require the user's explicit approval in the skill body.

Do not paste all 125 descriptions into the coding prompt. The index is the prompt line; the catalog is the directory.

## 6. Coding load_skill.v1 fallback

File: `neos/coding/tools/executor.py` `_load_skill`.

```python
catalog = default_catalog()
skill = catalog.get(name)
if skill is None or skill.disable_model_invocation:
    from neos.skills.markdown_catalog import k_skill_catalog
    catalog = k_skill_catalog()
    skill = catalog.get(name)
if skill is None or skill.disable_model_invocation:
    return ToolResult("denied", "unknown_skill", ...)
```

Then `load_markdown` on the catalog that hit.

Pins:

- `default_catalog().get("korea-weather") is None`
- `k_skill_catalog().get("korea-weather")` is not None
- coding `_load_skill(name="korea-weather")` returns ok with instruction body
- coding `_load_skill(name="xlsx-author")` stays `unknown_skill`
- coding `_load_skill(name="univer-sheets-headless")` stays `unknown_skill`
- coding `_load_skill(name="k-skill-setup")` is `unknown_skill`
- `list_skills()` (coding) includes `k-skill` and does not include `korea-weather`

## 7. Tests

| File | Pins |
|---|---|
| `tests/k_skill/test_skill_catalog.py` | roots, 125 names, exclusions, isolation from default/research/FSI/Univer |
| `tests/k_skill/test_skill_pack.py` | every dir has composed SKILL.md, name matches, instruction body present, no CLI stub heading |
| `tests/coding/tools/test_k_skill_load.py` | executor fallback |
| `tests/coding/prompts/test_builder.py` (extend) | prompt lists `k-skill`, not `korea-weather` |

## 8. What does not live here

| Path | Owner |
|---|---|
| `skills/financial-services/` | FSI pack |
| `skills/univer/` | Univer pack |
| `neos/coding/skills/{plan,commit,...}.md` | coding catalog except the new index |
| `neos/skills/builtin/` | BaseSkill |
| `../k-skill/packages/k-skill-proxy` | upstream AGPL server |
