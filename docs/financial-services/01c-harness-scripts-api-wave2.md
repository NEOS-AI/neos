# financial-services 하네스 · 스크립트 · API 분석

분석 범위는 `/Users/yeonwoosung/Desktop/financial-services` 의 지정 파일만이다. 인용은 해당 파일의 실제 문자열이며, 코드에 없는 동작은 추정하지 않는다.

근거 파일:

- `scripts/check.py`
- `scripts/validate.py`
- `scripts/deploy-managed-agent.sh`
- `scripts/orchestrate.py`
- `scripts/sync-agent-skills.py`
- `scripts/test-cookbooks.sh`
- `scripts/version_bump.py`
- `.claude-plugin/marketplace.json`
- `CLAUDE.md`
- `README.md`
- `managed-agent-cookbooks/README.md`
- `.github/workflows/plugin-validate.yml`
- `.github/workflows/version-bump.yml`
- `.github/workflows/secret-scan.yml`
- `.githooks/pre-commit`

필드 매핑·디스커버리 인용을 위해 같은 저장소의 `plugins/**/.claude-plugin/plugin.json`, `managed-agent-cookbooks/gl-reconciler/{agent.yaml,subagents/reader.yaml,steering-examples.json,README.md}`, `managed-agent-cookbooks/pitch-agent/agent.yaml` 도 대조했다.

---

## 1. 이중 표면 아키텍처 (Dual-surface)

한 소스에서 두 실행 표면을 제공한다. README:

> Everything here is available **two ways from one source**: install it as a Claude Cowork plugin, or deploy it through the Claude Managed Agents API behind your own workflow engine. Same system prompt, same skills — you choose where it runs.

`managed-agent-cookbooks/README.md`:

> Every agent in this repo ships **two ways**: as a Cowork plugin your analysts install today (see the vertical directories at repo root), and as a Claude Managed Agent template your platform team deploys behind your own workflow engine. **Same agent, same skills — pick your surface.** Each directory below is a deploy manifest that references the canonical system prompt and skills from the matching plugin, so there is one source of truth.

`CLAUDE.md` 가 그리는 레이아웃:

```
├── plugins/
│   ├── agent-plugins/               #   named agents — one self-contained plugin each
│   │   └── <slug>/
│   │       ├── .claude-plugin/plugin.json
│   │       ├── agents/<slug>.md     #   ← canonical system prompt (one source, two wrappers)
│   │       └── skills/              #   ← bundled copies, synced from vertical-plugins/
│   ├── vertical-plugins/            #   FSI verticals — skill sources, commands, MCPs
│   │   └── <vertical>/
│   │       ├── .claude-plugin/plugin.json
│   │       ├── commands/
│   │       ├── skills/
│   │       └── .mcp.json
│   └── partner-built/               #   partner plugins (LSEG, S&P Global)
├── managed-agent-cookbooks/         # CMA cookbooks (one dir per named agent)
│   └── <slug>/
│       ├── agent.yaml               #   system + skills → ../../plugins/agent-plugins/<slug>/...
│       ├── subagents/*.yaml         #   depth-1 leaf workers
│       ├── steering-examples.json
│       └── README.md                #   security tier + handoff notes
├── claude-for-msft-365-install/     # admin tooling for the Microsoft 365 add-in (separate from FSI plugins)
└── scripts/                         # deploy-managed-agent.sh, check.py, validate.py, orchestrate.py, sync-agent-skills.py
```

README 역할 표:

| 무엇 | 위치 |
|---|---|
| Agents (Cowork 플러그인 + CMA 래퍼가 같은 디렉터리를 참조) | `plugins/agent-plugins/<slug>/` |
| Skills 원본 | `plugins/vertical-plugins/<vertical>/skills/` |
| Skills 번들 복사본 | `plugins/agent-plugins/<slug>/skills/` |
| Commands | `plugins/vertical-plugins/<vertical>/commands/` |
| Connectors (MCP) | `plugins/vertical-plugins/financial-analysis/.mcp.json` |
| Managed-agent wrappers | `managed-agent-cookbooks/<slug>/` |

표면별 진입점:

- Cowork: Settings → Plugins → Add plugin, 레포 URL `https://github.com/anthropics/financial-services` 또는 `plugins/` 하위 zip.
- Claude Code:

```bash
claude plugin marketplace add anthropics/financial-services
claude plugin install financial-analysis@claude-for-financial-services
claude plugin install pitch-agent@claude-for-financial-services
```

- Managed Agents:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
scripts/deploy-managed-agent.sh gl-reconciler
```

명명된 에이전트 10개 (README 표와 cookbooks README 표가 일치):

| slug | 수직 플러그인 (cookbooks README) | CMA steering event (cookbooks README) | leaf workers |
|---|---|---|---|
| `pitch-agent` | investment-banking | `Build pitch book: <target> / <acquirer>, thesis: <text>` | researcher · modeler · **deck-writer** |
| `market-researcher` | equity-research | `Primer: <sector or theme>, angle: <text>` | sector-reader · comps-spreader · **note-writer** |
| `earnings-reviewer` | equity-research | `Process earnings: <ticker> <period>` | transcript-reader · model-updater · **note-writer** |
| `meeting-prep-agent` | wealth-management | `Briefing pack for <client-id>, meeting <event-id>` | profiler · news-reader · **pack-writer** |
| `model-builder` | financial-analysis | `Build <dcf\|lbo\|3-stmt> for <ticker>, assumptions: {...}` | data-puller · **builder** · auditor |
| `gl-reconciler` | financial-analysis | `Reconcile GL vs subledger, trade date <D>, classes: <list>` | reader · critic · **resolver** |
| `kyc-screener` | financial-analysis | `Screen onboarding packet <id>` | doc-reader · rules-engine · **escalator** |
| `valuation-reviewer` | private-equity | `Review portco valuations for fund <X> as of <date>` | package-reader · valuation-runner · **publisher** |
| `month-end-closer` | financial-analysis | `Close <entity> for period <YYYY-MM>` | ledger-reader · rollforward · **poster** |
| `statement-auditor` | private-equity | `Tie out statement batch <id> against <fund> NAV pack` | statement-reader · reconciler · **flagger** |

> **Bold** leaf = the only worker with `Write`.

수직 플러그인 (README): `financial-analysis` (core), `investment-banking`, `equity-research`, `private-equity`, `fund-admin`, `operations`, `claude-for-financial-advisors`, `lseg` (partner), `sp-global` (partner).

파트너·설치 툴링은 에이전트 이중 표면 밖에 있다. README:

> This is separate from the agents and vertical plugins above — it's the on-ramp that gets the add-in deployed in a tenant, after which the agents and skills here are what runs inside it.

---

## 2. 마켓플레이스 (`marketplace.json`)

경로: `.claude-plugin/marketplace.json`

최상위 키는 `name`, `owner`, `plugins` 세 개뿐이다. 마켓플레이스 자체 `version` 필드는 없다.

```json
{
  "name": "claude-for-financial-services",
  "owner": {
    "name": "Matt Piccolella"
  },
  "plugins": [ ... ]
}
```

각 플러그인 엔트리는 고정 4키: `name`, `displayName`, `source`, `description`.

`source` 는 레포 상대 경로. 세 종류:

1. `./plugins/vertical-plugins/<slug>`
2. `./plugins/agent-plugins/<slug>`
3. 예외 두 곳: `./plugins/partner-built/lseg`, `./plugins/partner-built/spglobal`, 그리고 루트의 `./claude-for-msft-365-install`

등록된 19개 (파일 순서 그대로):

| name | displayName | source |
|---|---|---|
| `financial-analysis` | Financial Analysis | `./plugins/vertical-plugins/financial-analysis` |
| `investment-banking` | Investment Banking | `./plugins/vertical-plugins/investment-banking` |
| `equity-research` | Equity Research | `./plugins/vertical-plugins/equity-research` |
| `private-equity` | Private Equity | `./plugins/vertical-plugins/private-equity` |
| `fund-admin` | Fund Administration | `./plugins/vertical-plugins/fund-admin` |
| `operations` | Operations | `./plugins/vertical-plugins/operations` |
| `pitch-agent` | Pitch Agent | `./plugins/agent-plugins/pitch-agent` |
| `market-researcher` | Market Researcher | `./plugins/agent-plugins/market-researcher` |
| `earnings-reviewer` | Earnings Reviewer | `./plugins/agent-plugins/earnings-reviewer` |
| `meeting-prep-agent` | Meeting Prep Agent | `./plugins/agent-plugins/meeting-prep-agent` |
| `model-builder` | Model Builder | `./plugins/agent-plugins/model-builder` |
| `gl-reconciler` | GL Reconciler | `./plugins/agent-plugins/gl-reconciler` |
| `kyc-screener` | KYC Screener | `./plugins/agent-plugins/kyc-screener` |
| `valuation-reviewer` | Valuation Reviewer | `./plugins/agent-plugins/valuation-reviewer` |
| `month-end-closer` | Month-End Closer | `./plugins/agent-plugins/month-end-closer` |
| `statement-auditor` | Statement Auditor | `./plugins/agent-plugins/statement-auditor` |
| `lseg` | LSEG | `./plugins/partner-built/lseg` |
| `sp-global` | S&P Global | `./plugins/partner-built/spglobal` |
| `claude-for-msft-365-install` | Claude for Microsoft 365 Install | `./claude-for-msft-365-install` |

Claude Code 설치 식별자는 `<plugin-name>@claude-for-financial-services` 이다. 마켓플레이스 `name` 이 `claude-for-financial-services` 이기 때문이다.

`check.py` 는 마켓플레이스 `source` 가 실제 `plugin.json` 을 가리키는지 검증한다:

```python
mp = ROOT / ".claude-plugin" / "marketplace.json"
for p in json.loads(mp.read_text()).get("plugins", []):
    src = (ROOT / p["source"]).resolve()
    if not (src / ".claude-plugin" / "plugin.json").is_file():
        err(f"marketplace: {p['name']} source -> {p['source']} (no plugin.json)")
```

CI `plugin-validate.yml` 은 마켓플레이스 파일을 공식 CLI 로 검증한다:

```bash
claude plugin validate .claude-plugin/marketplace.json
```

주석: Claude Code `2.1.143` 이 marketplace entry 의 `displayName` 을 처음으로 허용한다. `2.1.140` 이하는 unrecognized key 로 거절한다.

---

## 3. `plugin.json` 디스커버리

`CLAUDE.md` Key Files:

> - `marketplace.json`: Marketplace manifest - registers all plugins with source paths
> - `plugin.json`: Plugin metadata - name, description, version, and component discovery settings
> - `commands/*.md`: Slash commands invoked as `/plugin:command-name`
> - `skills/*/SKILL.md`: Detailed knowledge and workflows for specific tasks

실제 `plugin.json` 샘플에는 경로 오버라이드 키가 없다. 예: `plugins/agent-plugins/pitch-agent/.claude-plugin/plugin.json`

```json
{
  "name": "pitch-agent",
  "version": "0.1.1",
  "description": "Comps, precedents, LBO to a branded pitch deck, end to end",
  "author": {
    "name": "Anthropic FSI"
  }
}
```

`plugins/vertical-plugins/financial-analysis/.claude-plugin/plugin.json`:

```json
{
  "name": "financial-analysis",
  "version": "0.1.1",
  "description": "Core financial modeling and analysis tools: DCF, comps, LBO, 3-statement models, competitive analysis, and deck QC",
  "author": {
    "name": "Anthropic FSI"
  }
}
```

`claude-for-msft-365-install/.claude-plugin/plugin.json` 만 `author.email` 이 있다:

```json
{
  "name": "claude-for-msft-365-install",
  "description": "...",
  "version": "0.1.13",
  "author": {
    "name": "Anthropic",
    "email": "support@anthropic.com"
  }
}
```

대조한 `plugin.json` 어디에도 `agents`, `skills`, `commands`, `mcpServers` 같은 디스커버리 오버라이드 필드는 없다. 컴포넌트 발견은 디렉터리 규약이다.

| 규약 경로 | 누가 쓰는가 |
|---|---|
| `<plugin>/.claude-plugin/plugin.json` | marketplace source 검증, version-bump, `claude plugin validate` |
| `plugins/agent-plugins/<slug>/agents/*.md` | `check.py` frontmatter (`name` + `description`), 캐논 시스템 프롬프트 |
| `plugins/agent-plugins/<slug>/skills/<name>/` | 번들 스킬. `check.py` 가 vertical 원본과 `filecmp.dircmp` |
| `plugins/vertical-plugins/<vertical>/skills/<name>/` | 스킬 소스 오브 트루스. `sync-agent-skills.py` 인덱스 |
| `plugins/vertical-plugins/<vertical>/commands/*.md` | 슬래시 커맨드. README: `/comps`, `/dcf`, `/earnings`, `/ic-memo` |
| `plugins/vertical-plugins/<vertical>/.mcp.json` | MCP 커넥터 (README: financial-analysis 에 중앙화) |

`check.py` JSON 파싱 glob:

```python
json_globs = [
    ".claude-plugin/marketplace.json",
    "plugins/**/.claude-plugin/plugin.json",
    "managed-agent-cookbooks/*/steering-examples.json",
]
```

이 glob 은 `claude-for-msft-365-install/.claude-plugin/plugin.json` 을 **파싱하지 않는다**. 반면 marketplace source 검사는 그 경로의 `plugin.json` 존재는 확인한다.

`version_bump.py` 의 플러그인 발견은 더 넓다:

```python
def all_plugin_jsons() -> list[Path]:
    """Every <plugin>/.claude-plugin/plugin.json in the repo."""
    return sorted(
        p for p in ROOT.glob("**/.claude-plugin/plugin.json")
        if ".git/" not in str(p)
    )
```

`plugin_root` = `plugin_json.parent.parent` 즉 `<root>/.claude-plugin/plugin.json` → `<root>`.

CI `plugin-validate.yml` 의 플러그인 열거는 `plugins/` 아래로 제한된다:

```bash
find plugins -path '*/.claude-plugin/plugin.json' | sort
plugin_dir="$(dirname "$(dirname "$manifest")")"
claude plugin validate "$plugin_dir"
```

따라서 `claude-for-msft-365-install` 은 marketplace 검증에는 포함되지만, `find plugins` 루프의 `claude plugin validate <plugin_dir>` 대상은 아니다.

`check.py` agent.md 프론트매터 검사 glob:

```python
for md in sorted(PLUGINS.glob("agent-plugins/*/agents/*.md")):
```

필수 YAML 키: `name`, `description`. 선행 `---` 필수. `text.split("---", 2)` 로 파싱.

agent.md 가 백틱으로 참조하는 kebab-case 스킬이 자기 번들에 있는지 검사하는 정규식:

```python
re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", md.read_text())
```

매칭 예: `` `gl-recon` ``, `` `comps-analysis` ``. 하이픈이 없는 단일 토큰은 매칭하지 않는다. 히트가 `src_by_name`(vertical 스킬 이름)에 있고 해당 에이전트 `skills/` 번들에 없으면 에러.

---

## 4. 스킬 동기화 알고리즘 (`sync-agent-skills.py`)

스크립트 docstring:

> Agent plugins under `plugins/agent-plugins/<slug>/skills/<name>/` are vendored copies of `plugins/vertical-plugins/*/skills/<name>/`. The vertical copy is the source of truth; run this after editing a skill there to propagate the change into every agent that bundles it.

알고리즘 (파일 전체, 분기는 없다):

1. `VERTICALS = ROOT / "plugins" / "vertical-plugins"`
2. `src_by_name: dict[str, Path] = {}`
3. `VERTICALS.glob("*/skills/*")` 중 디렉터리만 인덱싱. **키는 스킬 디렉터리 이름(`sk.name`)뿐** 이다. 수직이 달라도 이름이 같으면 나중에 본 경로가 덮어쓴다.
4. `AGENTS.glob("*/skills/*")` 를 정렬 순회로 돌린다.
5. 번들 이름이 `src_by_name` 에 없으면 `missing` 에 상대경로를 넣고 continue.
6. 있으면 `shutil.rmtree(bundled)` 후 `shutil.copytree(src, bundled)`. 부분 머지가 아니라 **디렉터리 전체 교체**.
7. `synced` 카운트 출력: `synced {n} bundled skill dir(s) from vertical-plugins/`
8. `missing` 가 비어 있지 않으면 stderr 에 `WARN: no vertical source found for:` 와 각 경로를 찍고 **exit 1**.

`check.py` 4b 는 같은 인덱스 규칙으로 drift 를 잡는다. 동기화가 아니라 비교만 한다:

```python
src_by_name = {p.name: p for p in PLUGINS.glob("vertical-plugins/*/skills/*") if p.is_dir()}
for bundled in sorted(PLUGINS.glob("agent-plugins/*/skills/*")):
    ...
    cmp = filecmp.dircmp(src, bundled)
    if cmp.diff_files or cmp.left_only or cmp.right_only:
        err(
            f"bundled-skill: {rel(bundled)}: drifted from {rel(src)} "
            f"(run scripts/sync-agent-skills.py)"
        )
```

`filecmp.dircmp` 는 기본이 1-level 이다. `diff_files` / `left_only` / `right_only` 만 본다. 하위 디렉터리 재귀 비교(`subdirs`)는 이 조건에 포함되지 않는다.

`meeting-prep-agent` 번들에는 `client-report`, `client-review`, `investment-proposal` 이 있다. 이 이름들이 `vertical-plugins/*/skills/` 에 없으면 `sync-agent-skills.py` 는 missing 으로 exit 1, `check.py` 는 `no vertical-plugins source named '...'` 로 실패한다.

---

## 5. `check.py` 린트 규칙

진입 시 `ensure_hooks_installed()` 가 **가장 먼저** 돈다 (pyyaml 미설치로 exit 2 하기 전).

```python
want = ".githooks"
cur = subprocess.run(
    ["git", "-C", str(ROOT), "config", "--get", "core.hooksPath"],
    ...
).stdout.strip()
if cur != want:
    subprocess.run(
        ["git", "-C", str(ROOT), "config", "core.hooksPath", want],
        check=True, capture_output=True,
    )
```

실패는 삼킨다 (`except (subprocess.SubprocessError, OSError): pass`). pyyaml 없으면 `sys.exit(2)`.

규칙 목록 (파일 주석 + 구현):

### 5.1 YAML parse

`MANAGED.rglob("*.yaml")` → `yaml.safe_load`. 실패 시 `YAML parse: {rel}: {e}`.

`MANAGED = ROOT / "managed-agent-cookbooks"`.

### 5.2 JSON parse

위 `json_globs` 세 패턴. `json.JSONDecodeError` → `JSON parse: {rel}: {e}`.

### 5.3 agent.md frontmatter

`plugins/agent-plugins/*/agents/*.md`

- 선행 `---` 없으면 `frontmatter: ... missing leading ---`
- `name`, `description` 없으면 `missing '{k}'`
- split/YAML 실패는 예외 메시지

### 5.4 reference resolution (`check_refs`)

모든 `managed-agent-cookbooks/**/*.yaml` 에 대해, yaml 기준 디렉터리 `base = yml.parent`:

| 필드 | 조건 | 존재 검사 |
|---|---|---|
| `system.file` | `system` 이 dict 이고 `file` 키 | `(base / file).resolve().is_file()` |
| `skills[].path` | dict + `path` | `(base / path).resolve().exists()` (파일 또는 디렉터리) |
| `skills[].from_plugin` | dict + `from_plugin` | `(base / from_plugin).resolve() / "skills"` 가 디렉터리 |
| `callable_agents[].manifest` | dict + `manifest` | `(base / manifest).resolve().is_file()` |

에러 포맷:

```
ref: {yml}: system.file -> {file} (not found)
ref: {yml}: skills.path -> {path} (not found)
ref: {yml}: skills.from_plugin -> {from_plugin} (no skills/ dir)
ref: {yml}: callable_agents.manifest -> {manifest} (not found)
```

### 5.5 bundled-skill drift (4b)

위 4절. 원본 없으면 `bundled-skill: {rel}: no vertical-plugins source named '{name}'`.

### 5.6 agent-prose skill refs (4b2)

백틱 kebab-case 가 vertical 스킬 이름과 같고 자기 번들에 없으면:

```
agent-prose: {md}: references `{ref}` but plugins/agent-plugins/{slug}/skills/{ref}/ is not bundled
```

`slug = md.parents[1].name`.

### 5.7 marketplace source (4c)

섹션 2 인용.

### 5.8 쿡북 필수 파일

`managed-agent-cookbooks/` 의 각 디렉터리에 대해 세 파일이 파일이어야 한다:

```python
for req in ("agent.yaml", "README.md", "steering-examples.json"):
    if not (d / req).is_file():
        err(f"missing: {rel(d)}/{req}")
```

### 5.9 PowerShell ASCII

주석 상수:

```python
ASCII_ONLY_SUFFIXES = {".ps1", ".psm1", ".psd1"}
```

실제 루프는 `ROOT.rglob("*.ps1")` 만. `.psm1` / `.psd1` 는 스캔하지 않는다. `.git`, `node_modules` 경로 부분은 skip.

- BOM `b"\xef\xbb\xbf"` 로 시작하면 그 파일은 통과 (UTF-8 로 디코드하라는 신호).
- BOM 없고 어떤 바이트가 `> 0x7F` 이면 해당 줄에서 에러 하나 찍고 `break` (파일당 1건).

```
non-ascii: {rel}:{lineno}: byte(s) {0x..} in a .ps1 with no UTF-8 BOM -- Windows PowerShell 5.1 will mis-decode this and may fail to parse the file. Use ASCII (-- for an em dash) or add a BOM.
```

종료: 에러 있으면 stderr 에 `FAIL — {n} issue(s) across {checked} file(s):` 후 각 `✗`, `sys.exit(1)`. 없으면 `OK — {checked} file(s) checked, 0 issues.`

`checked` 는 YAML 파일, JSON 파일, agent.md, `.ps1` 만 증가시킨다. ref 검사·번들 drift·marketplace·필수 파일은 `checked` 를 올리지 않는다.

---

## 6. `validate.py` vs `check.py` vs `test-cookbooks.sh`

세 스크립트는 겹치지 않는 레이어를 담당한다.

### 6.1 `check.py` — 정적 레포 린트

매니페스트 파싱, 교차 참조, 스킬 drift, marketplace `plugin.json` 존재, 쿡북 필수 파일, `.ps1` ASCII. 네트워크 호출 없음. 배포 페이로드를 만들지 않는다.

### 6.2 `validate.py` — 워커 JSON 출력 스키마

docstring:

> Harness-side schema validation for managed-agent worker output.
>
> Usage: `validate.py <output.json> <schema.json|schema.yaml>`
> Exits 0 on valid, 1 on invalid (message to stderr).
>
> The CMA API does not enforce structured output today, so the deploy harness
> runs this between a reader subagent and the orchestrator. Schemas live in each
> subagent yaml under `output_schema:` — the deploy script extracts them.

구현:

```python
def _load(path: Path):
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(text)
    return json.loads(text)

def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    instance = _load(Path(sys.argv[1]))
    schema = _load(Path(sys.argv[2]))
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as e:
        print(f"INVALID: {e.message} at {'/'.join(str(p) for p in e.absolute_path)}", file=sys.stderr)
        return 1
    print("OK")
    return 0
```

argv 개수 오류는 exit 2. 스키마 파일 경로를 받는 독립 CLI 이며, 쿡북 디렉터리를 순회하지 않는다.

`deploy-managed-agent.sh` 본문은 `validate.py` 를 **호출하지 않는다**. `output_schema` 는 POST 전에 삭제만 한다 (`del(.output_schema)`). 스크립트 헤더 주석은 "thin validation wrapper" 를 말하지만, 그 wrapper 를 생성하는 코드는 이 파일에 없다. `gl-reconciler/subagents/reader.yaml` 주석:

> Not an API field — consumed by `scripts/validate.py`, which validates worker output against this schema before returning it to the orchestrator.

즉 `output_schema` 는 CMA POST 필드가 아니라 하네스 쪽 계약이다. 런타임에 누가 `validate.py` 를 호출하는지는 이 스크립트들에 구현되어 있지 않다.

### 6.3 `test-cookbooks.sh` — dry-run 페이로드 어서션

```bash
# Dry-run every managed-agent cookbook and assert the resolved POST /v1/agents
# bodies are well-formed: valid JSON, depth-1, non-empty system prompts, no
# output_schema. Exits non-zero if any cookbook fails.
```

루프:

```bash
for d in "$ROOT"/managed-agent-cookbooks/*/; do
  slug=$(basename "$d")
  if ! bash "$ROOT/scripts/deploy-managed-agent.sh" "$slug" --dry-run 2>&1 | tail -n +2 | python3 -c "..." "$slug"; then
    echo "  ✗ $slug" >&2
    fail=1
  fi
done
exit $fail
```

`tail -n +2` 는 dry-run 의 첫 줄 주석을 버린다:

```
# --dry-run: resolved POST /v1/agents bodies (subagents first, orchestrator last)
```

파이썬 어서션 (stdin = `jq -s '.'` 로 만든 배열):

```python
b=json.load(sys.stdin)
errs=[]
for i,x in enumerate(b):
    if not x.get('system'): errs.append(f'{x.get("name")}: empty system')
    if i<len(b)-1 and x.get('callable_agents'): errs.append(f'{x.get("name")}: depth>1 (subagent has callable_agents)')
if 'output_schema' in json.dumps(b): errs.append('output_schema leaked into a body')
```

세 검사:

1. 모든 바디의 `system` 이 truthy (빈 문자열/누락 실패).
2. 마지막 바디를 제외한 항목이 truthy `callable_agents` 를 가지면 depth>1. 빈 리스트 `[]` 는 Python 에서 falsy 이므로 통과.
3. 직렬화된 JSON 문자열에 부분문자열 `output_schema` 가 있으면 실패.

`check.py` 가 파일 존재·파싱을 보고, `test-cookbooks.sh` 가 **해석된 POST 바디** 를 본다. `validate.py` 는 배포 후 워커 출력용이다.

---

## 7. `deploy-managed-agent.sh` API · 헤더 · 치환 · dry-run · 재귀 `create_agent`

### 7.1 용법·환경

```
Usage: scripts/deploy-managed-agent.sh <slug>
  e.g. scripts/deploy-managed-agent.sh gl-reconciler
```

```bash
ROLE="${1:?usage: deploy-managed-agent.sh <slug> [--dry-run]}"
DRY_RUN=0; [[ "${2:-}" == "--dry-run" ]] && DRY_RUN=1
DIR="$ROOT/managed-agent-cookbooks/$ROLE"
API="${ANTHROPIC_API_BASE:-https://api.anthropic.com}"
[[ $DRY_RUN -eq 1 ]] || : "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY must be set}"
[[ -f "$DIR/agent.yaml" ]] || { echo "no manifest at $DIR/agent.yaml" >&2; exit 1; }
```

`REPO_SLUG`:

```bash
REPO_SLUG="${REPO_SLUG:-$(basename -s .git "$(git config --get remote.origin.url)")}"
: "${REPO_SLUG:?cannot derive REPO_SLUG from git remote; set REPO_SLUG env var}"
COOKBOOK_TAG="${REPO_SLUG}/${ROLE}"
```

의존: `jq`, `python3` + `pyyaml`. dry-run 이 아니면 `ANTHROPIC_API_KEY`.

기타 env:

- `ANTHROPIC_API_BASE` (기본 `https://api.anthropic.com`)
- `SKILL_TITLE_PREFIX` (`display_title` 접두)
- `DEPLOY_DEBUG` 가 non-empty 이면 `{name, callable_agents}` 를 stderr 에 compact JSON 으로 출력

### 7.2 엔드포인트와 베타 헤더

에이전트 POST 헬퍼 `req()`:

```bash
req() {
  curl -sS -H "x-api-key: $ANTHROPIC_API_KEY" \
           -H "anthropic-version: 2023-06-01" \
           -H "anthropic-beta: managed-agents-2026-04-01" \
           -H "content-type: application/json" "$@"
}
```

호출:

```bash
resp=$(req -X POST "$API/v1/agents" -d "$json")
id=$(jq -r '.id // empty' <<<"$resp")
ver=$(jq -r '.version // 1' <<<"$resp")
```

스킬 업로드는 **다른 베타 헤더 + multipart** 이다. 주석:

> `/v1/skills` uses its own beta header and multipart, not the managed-agents JSON path

```bash
resp=$(curl -sS "$API/v1/skills" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "anthropic-beta: skills-2025-10-02" \
  -F "display_title=${SKILL_TITLE_PREFIX:-}$(basename "$path")" \
  -F "files[]=@$zip")
id=$(jq -r '.id // empty' <<<"$resp")
cached=$(printf '{"type":"custom","skill_id":"%s","version":"latest"}' "$id")
```

zip:

```bash
zip="$(mktemp -t skill).zip"
(cd "$(dirname "$path")" && zip -qr "$zip" "$(basename "$path")")
```

정리:

| 메서드 | URL | beta | content-type | 응답에서 쓰는 필드 |
|---|---|---|---|---|
| POST | `$API/v1/skills` | `skills-2025-10-02` | multipart (`display_title`, `files[]`) | `.id` → `skill_id` |
| POST | `$API/v1/agents` | `managed-agents-2026-04-01` | `application/json` | `.id`, `.version // 1` |

공통: `x-api-key`, `anthropic-version: 2023-06-01`.

### 7.3 env 치환 안전 정규식 (`yaml2json`)

YAML 을 JSON 으로 바꾸기 **전에** 원문에서 `${NAME}` 을 치환한다.

```python
SAFE = re.compile(r"^[A-Za-z0-9._/:@-]*$")
def sub(m):
    name = m.group(1)
    v = os.environ.get(name)
    if v is None:
        return m.group(0)
    if not SAFE.fullmatch(v):
        sys.exit(f"refusing ${{{name}}}: value contains characters outside [A-Za-z0-9._/:@-]")
    return v
t = open(sys.argv[1]).read()
t = re.sub(r"\$\{([A-Z0-9_]+)\}", sub, t)
json.dump(yaml.safe_load(t), sys.stdout)
```

규칙:

- 패턴: `\$\{([A-Z0-9_]+)\}` — `${` + 대문자/숫자/언더스코어 + `}`. `$FOO` 나 `${foo}` 는 치환하지 않는다.
- 미설정 변수는 원문 `${NAME}` 을 그대로 남긴다 (`return m.group(0)`).
- 설정됐으면 `SAFE.fullmatch`. 허용: `A-Za-z0-9._/:@-` (빈 문자열 포함, `*` 퀀티파이어).
- 거부 시 process exit, 메시지: `refusing ${NAME}: value contains characters outside [A-Za-z0-9._/:@-]`

매니페스트 예 (`gl-reconciler/agent.yaml`): `url: ${GL_MCP_URL}`, `url: ${SUBLEDGER_MCP_URL}`. `pitch-agent/agent.yaml`: `url: "${CAPIQ_MCP_URL}"`, `url: "${DALOOPA_MCP_URL}"`.

### 7.4 스킬 캐시와 dry-run 스킬

```bash
SKILL_CACHE_FILE="$(mktemp -t skillcache)"
trap 'rm -f "$SKILL_CACHE_FILE"' EXIT
```

캐시 키는 `basename "$path"` 이다. 서로 다른 경로라도 디렉터리 이름이 같으면 재사용한다.

dry-run:

```bash
cached=$(printf '{"type":"custom","skill_id":"DRYRUN_%s","version":"latest"}' "$key")
```

실배포: zip 업로드 → `.id` 없으면 stderr 에 `POST /v1/skills failed for $path:` 후 응답 덤프, exit 1.

### 7.5 `resolve_manifest` / `inline_system`

`from_plugin` 확장:

```bash
fp=$(jq -r '.skills[]? | select(.from_plugin) | .from_plugin' <<<"$json" | head -1)
```

**첫 번째 `from_plugin` 만** 디렉터리로 펼친다. 그 플러그인 `skills/*/` 각각을 `{__upload: <abs path>}` 로 만든다. 그 다음:

```jq
.skills = ((.skills // [] | map(select(.from_plugin | not))) + $e)
```

모든 `from_plugin` 엔트리를 제거하고, 펼친 목록을 뒤에 붙인다. 두 번째 `from_plugin` 은 삭제만 되고 업로드되지 않는다.

이어서 `path` 는 `{__upload: $base + "/" + .path}` 로 바뀐다. 이미 `__upload` 인 항목은 유지. 그 외(이미 API 형태인 `{type, skill_id, version}` 등)는 그대로.

`inline_system`:

- `system` 이 object 이면 `system.file`, `system.text`, `system.append` 를 읽는다.
- `file` 이 있으면 `$base/$sysfile` 을 `cat`. 없으면 exit `system.file not found: ...`.
- `text` 가 있으면 그것이 초기 `body`. file 이 있으면 file 내용으로 **교체** (`body="$(cat ...)"`). text+file 을 concatenate 하지 않는다.
- `append` 가 있으면 `body` + `\n\n` + append.
- 결과를 `.system = <string>` 으로 넣는다.
- `system` 이 object 가 아니면 JSON 을 그대로 둔다.

### 7.6 재귀 `create_agent`

```bash
create_agent() {
  local file="$1" base json sub_ids skills_json
  base="$(cd "$(dirname "$file")" && pwd)"
  json=$(resolve_manifest "$file")
  json=$(inline_system "$json" "$base")

  skills_json="[]"
  while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    [[ -d "$p" ]] || { echo "skill path not found: $p" >&2; exit 1; }
    skills_json=$(jq ". + [$(upload_skill "$p")]" <<<"$skills_json")
  done < <(jq -r '.skills[]? | select(.__upload) | .__upload' <<<"$json")
  json=$(jq --argjson s "$skills_json" '.skills=$s' <<<"$json")

  sub_ids="[]"
  while IFS= read -r m; do
    [[ -z "$m" ]] && continue
    local out sid sver
    out=$(create_agent "$base/$m")
    sid=${out%% *}; sver=${out##* }
    sub_ids=$(jq --arg i "$sid" --argjson v "$sver" '. + [{type:"agent", id:$i, version:$v}]' <<<"$sub_ids")
  done < <(jq -r '.callable_agents[]?.manifest // empty' <<<"$json")
  json=$(jq --argjson c "$sub_ids" '.callable_agents=$c | del(.output_schema)' <<<"$json")
  json=$(jq --arg ck "$COOKBOOK_TAG" '.metadata = ((.metadata // {}) + {anthropic_cookbook: $ck})' <<<"$json")
  ...
}
```

순서:

1. 매니페스트 resolve + system inline.
2. `__upload` 스킬을 디렉터리인지 확인 후 업로드. `.skills` 를 업로드 결과 배열로 **교체** (path/from_plugin 이 아닌 기존 skill 객체도 이 교체로 사라진다 — 교체 집합은 `__upload` 항목뿐이다).
3. 각 `callable_agents[].manifest` 에 대해 `create_agent "$base/$m"` **재귀**. 깊이 제한 코드는 없다.
4. 자식 반환값 `"$id $ver"` 를 `{type:"agent", id, version}` 으로 쌓는다. `--argjson v` 이므로 version 은 JSON 숫자여야 한다 (dry-run 은 `1`).
5. `.callable_agents` 를 그 배열로 교체하고 `.output_schema` 삭제.
6. `.metadata.anthropic_cookbook = $COOKBOOK_TAG` (`<repo-slug>/<role>`). 기존 metadata 키는 유지 (`// {}` + add).

실배포 성공 stdout: `"$id $ver"`. 실패: `POST /v1/agents failed for <name>:`.

dry-run 분기:

```bash
if [[ $DRY_RUN -eq 1 ]]; then
  echo "$json" >>"$DRY_OUT"
  jq -r '"DRYRUN_" + .name + " 1"' <<<"$json"; return
fi
```

자식이 먼저 `DRY_OUT` 에 append 되므로 배열 순서는 **subagents first, orchestrator last**.

최상위 dry-run:

```bash
if [[ $DRY_RUN -eq 1 ]]; then
  DRY_OUT="$(mktemp)"
  create_agent "$DIR/agent.yaml" >/dev/null
  echo "# --dry-run: resolved POST /v1/agents bodies (subagents first, orchestrator last)"
  jq -s '.' "$DRY_OUT"
  rm -f "$DRY_OUT"
  exit 0
fi
```

실배포 최상위 stdout:

```
deployed: $ROLE
agent id: $AGENT_ID
cookbook: $COOKBOOK_TAG
console:  https://console.anthropic.com/agents/$AGENT_ID
```

헤더 주석이 말하는 해석 목록:

```
system: {file: ...}                  -> inlined string
skills: [{path: ...}]                -> uploaded, referenced by skill_id
callable_agents: [{manifest: ...}]   -> created first, referenced by agent id
```

---

## 8. `orchestrate.py` — `handoff_request` 프로토콜 · 허용 목록 · 스키마 · 위협 모델

파일 상단:

> REFERENCE ONLY — replace with your firm's workflow engine (Temporal, Airflow, Guidewire event bus). This script shows the shape of the loop, not a production implementation.

`managed-agent-cookbooks/README.md`:

> Named agents never call each other directly. When one agent needs another, it emits a `handoff_request` in its output; `../scripts/orchestrate.py` (or your Temporal/Airflow/Guidewire event bus) routes it as a new steering event to the target session. The reference script hard-allowlists targets and schema-validates payloads — see its header comment for the threat model.

### 8.1 위협 모델 (헤더 전문)

> Security note: handoff requests are surfaced in the orchestrator's text output, which is downstream of untrusted-document readers. An attacker who controls a processed document could embed a literal handoff_request blob that, if echoed, would be parsed here. This script mitigates by (a) hard-allowlisting target_agent against the deployed slugs and (b) schema-validating the payload before steering. In production, prefer emitting handoffs via a dedicated tool call or a typed SSE event the model cannot produce by quoting document text.

완화 두 가지가 코드에 있다. 권고(툴 콜 / typed SSE)는 구현되어 있지 않다.

### 8.2 추출 정규식

```python
HANDOFF_RE = re.compile(
    r'\{"type":\s*"handoff_request".*?\}', re.DOTALL
)
```

- 리터럴 `{"type":` + 선택적 공백 + `"handoff_request"` 로 시작.
- `re.DOTALL` + `.*?\}` — 첫 `}` 에서 끝. payload 가 중첩 객체이면 첫 닫는 중괄호에서 잘려 `json.loads` 가 실패하고 `None` 을 반환한다.
- 키 순서가 `"type"` 이 아닌 블롭, 작은따옴표 JSON 은 매칭하지 않는다.

```python
def extract_handoff(text: str) -> dict | None:
    m = HANDOFF_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    target = obj.get("target_agent")
    payload = obj.get("payload")
    if target not in ALLOWED_TARGETS:
        return None
    try:
        jsonschema.validate(instance=payload, schema=HANDOFF_PAYLOAD_SCHEMA)
    except jsonschema.ValidationError:
        return None
    return {"target_agent": target, "payload": payload}
```

`type` 필드 값은 정규식에만 있고, `json.loads` 이후 다시 검사하지 않는다. `target_agent` / `payload` 외 키는 무시된다.

### 8.3 허용 목록

```python
ALLOWED_TARGETS = {
    "pitch-agent", "market-researcher", "earnings-reviewer", "meeting-prep-agent",
    "model-builder", "gl-reconciler", "kyc-screener",
    "valuation-reviewer", "month-end-closer", "statement-auditor",
}
```

쿡북 10 slug 와 동일. allowlist 밖이면 예외 없이 `None`.

### 8.4 페이로드 스키마

```python
HANDOFF_PAYLOAD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["event"],
    "properties": {
        "event": {"type": "string", "maxLength": 2000},
        "context_ref": {"type": "string", "maxLength": 256,
                        "pattern": r"^[A-Za-z0-9 ._/:#-]+$"},
    },
}
```

- 객체만. 추가 속성 금지.
- 필수: `event` (string, ≤ 2000).
- 선택: `context_ref` (string, ≤ 256, 문자 클래스 `A-Za-z0-9 ._/:#-`).
- `payload` 가 `None` 이면 jsonschema 가 실패해 핸드오프는 버려진다.

`gl-reconciler/subagents/reader.yaml` 의 `evidence_refs` 항목 패턴과 `context_ref` 패턴이 같다: `^[A-Za-z0-9 ._/:#-]+$`.

기대 블롭 형태 (정규식 + 필드에서 역산, 파일에 예시 JSON 은 없음):

```json
{"type": "handoff_request", "target_agent": "<slug>", "payload": {"event": "...", "context_ref": "..."}}
```

중첩 없이 한 레벨의 `}` 로 끝나야 정규식이 전체를 가져간다.

### 8.5 이벤트 루프

```python
def run(source_session_id: str, agent_ids: dict[str, str]) -> None:
    """agent_ids maps slug -> deployed CMA agent_id."""
    client = anthropic.Anthropic()
    # /v1/agents is a preview endpoint; SDK type stubs don't cover it yet.
    with client.beta.agents.sessions.stream(session_id=source_session_id) as stream:  # type: ignore[attr-defined]
        for event in stream:
            if event.type != "message_delta" or not getattr(event, "text", None):
                continue
            handoff = extract_handoff(event.text)
            if not handoff:
                continue
            target_slug = handoff["target_agent"]
            target_id = agent_ids.get(target_slug)
            if not target_id:
                continue
            client.beta.agents.sessions.steer(  # type: ignore[attr-defined]
                agent_id=target_id,
                input=handoff["payload"]["event"],
            )
```

- 스트림: `client.beta.agents.sessions.stream(session_id=...)`.
- 처리하는 이벤트: `event.type == "message_delta"` 이고 `event.text` 가 truthy.
- steer: `client.beta.agents.sessions.steer(agent_id=target_id, input=payload["event"])`.
- `context_ref` 는 스키마에만 있고 **steer 호출에 전달되지 않는다**.
- `agent_ids` 에 slug 가 없으면 조용히 skip (allowlist 통과 후에도).

`__main__`:

```python
run(
    source_session_id=os.environ["SOURCE_SESSION_ID"],
    agent_ids=json.loads(os.environ.get("AGENT_IDS", "{}")),
)
```

필수 env: `SOURCE_SESSION_ID`. 선택: `AGENT_IDS` (기본 `{}`).

GL Reconciler README 핸드오프 서술:

> **Handoff:** to feed verified breaks into Month-End Closer, the orchestrator emits a `handoff_request` for `month-end-closer` in its final output; `scripts/orchestrate.py` (or your Temporal/Airflow worker) routes it as a new steering event.

---

## 9. `version_bump.py` + pre-commit + GitHub Action

### 9.1 목적

> A plugin's `.claude-plugin/plugin.json` `version` gates update delivery to already-installed users (Claude Code only re-delivers a plugin when its version changes). This script guarantees that any plugin modified on a branch ends up exactly one patch ahead of `main` — bumped once, not once per commit.

모드:

| 모드 | 변이 | 변경 집합 | 사용처 |
|---|---|---|---|
| `--apply` | `plugin.json` 을 쓰고 `git add` | **staged** (`git diff --cached --name-only`) | `.githooks/pre-commit` |
| `--check` | 읽기 전용, 위반 시 exit 1 | `base...HEAD` | `.github/workflows/version-bump.yml` |

base 해석 순서: `--base` → `origin/main` → `main`.

```python
def resolve_base(explicit: str | None) -> str | None:
    for ref in (explicit, "origin/main", "main"):
        if ref and git_ok("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"):
            return ref
    return None
```

base 가 없으면 skip, exit 0:

```
[version-bump] no base ref found; skipping.
```

주석: "Never block a commit over this; CI has full history as the backstop."

semver: `x.y.z` 세 정수. 파싱 실패 시 `patch_bump` 는 `"0.0.1"`. apply 에서 base 도 working 도 없으면 `"0.0.0"` 을 bump 해 `0.0.1`.

```python
def is_ahead(work: str | None, base: str | None) -> bool:
    if base is None:
        # Plugin is new on this branch — nothing to be 'ahead' of.
        return True
    wv, bv = parse_semver(work or ""), parse_semver(base)
    if wv is None or bv is None:
        return (work or "") != base
    return wv > bv
```

새 플러그인(base 에 파일 없음)은 bump 의무가 없다.

changed plugin 판정: `plugin.json` 의 플러그인 루트 상대경로가, 변경 파일과 같거나 그 parent 이거나 `startswith(f"{root_rel}/")`.

`--apply` 는 아직 ahead 가 아닌 staged 플러그인만 `base + 1` 로 쓰고 `git add`. 이미 ahead 이면 no-op (브랜치당 한 번).

`--check` 실패 메시지:

```
{plugin_root}: changed but version not bumped ({bv} -> {work}). Bump .claude-plugin/plugin.json version (or run scripts/check.py once to install the pre-commit hook).
```

exit: 0 clean, 1 `--check` 위반, 2 는 docstring 에만 있고 `main()` 은 argparse/git 예외가 아니면 0/1.

출력 JSON 포맷: `json.dumps(data, indent=2) + "\n"`.

### 9.2 `.githooks/pre-commit`

```bash
#!/usr/bin/env bash
# Auto patch-bump any plugin with staged changes so it ends up exactly one
# patch ahead of main — bumped once per branch, not once per commit.
#
# Install (one-time per clone):  git config core.hooksPath .githooks
# (scripts/check.py self-installs this for you on first run.)
#
# Bypass for a single commit:    git commit --no-verify
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[pre-commit] python3 not found; skipping version-bump." >&2
  exit 0
fi

python3 "$REPO_ROOT/scripts/version_bump.py" --apply
```

Husky/Node 없음. `CLAUDE.md`: `git config core.hooksPath .githooks — no Husky/Node`.

### 9.3 `.github/workflows/version-bump.yml`

```yaml
name: version-bump
on:
  pull_request:
permissions:
  contents: read
jobs:
  version-bump:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Check plugin version bumps
        env:
          BASE_REF: ${{ github.base_ref }}
        run: |
          set -euo pipefail
          git fetch --no-tags --depth=1 origin "$BASE_REF"
          python3 scripts/version_bump.py --check --base "origin/$BASE_REF"
```

PR 전용. `fetch-depth: 0` 후 base 를 한 번 더 fetch. `--base origin/$BASE_REF` (보통 `origin/main`).

---

## 10. CMA 필드 매핑

`managed-agent-cookbooks/README.md` "Manifest vs API":

> The `agent.yaml` files use the real `POST /v1/agents` field names with a few conveniences the deploy script resolves:

| Manifest convention | Resolves to |
|---|---|
| `system: {file: ../../plugins/agent-plugins/<slug>/agents/<slug>.md, append: "..."}` | `system: "<inlined contents + append>"` |
| `system: {text: "..."}` | `system: "<text>"` |
| `skills: [{from_plugin: ../../plugins/agent-plugins/<slug>}]` | uploads every `skills/*` under that dir → `[{type: custom, skill_id: ...}, ...]` |
| `skills: [{path: ../../...}]` | `skills: [{type: custom, skill_id: <uploaded-id>}]` |
| `callable_agents: [{manifest: ./subagents/x.yaml}]` | `callable_agents: [{type: agent, id: <created-id>, version: latest}]` |

스크립트가 실제로 넣는 값:

스킬 (실배포):

```json
{"type":"custom","skill_id":"<POST /v1/skills .id>","version":"latest"}
```

스킬 (dry-run):

```json
{"type":"custom","skill_id":"DRYRUN_<basename>","version":"latest"}
```

서브에이전트:

```jq
{type:"agent", id:$i, version:$v}
```

`$v` 는 API `.version // 1` 또는 dry-run 리터럴 `1` (숫자). README 표의 `version: latest` 와 달리 **에이전트 쪽 version 은 숫자** 이다. `latest` 는 스킬 객체에만 쓰인다.

추가로 스크립트가 쓰는 필드:

- `metadata.anthropic_cookbook` = `"${REPO_SLUG}/${ROLE}"`
- `output_schema` 삭제 (API 로 나가지 않음)

매니페스트에 그대로 남는 필드 (스크립트가 건드리지 않음): `name`, `model`, `tools`, `mcp_servers`, 이미 문자열인 `system`.

`gl-reconciler/agent.yaml` 원문 필드:

```yaml
name: gl-reconciler
model: claude-opus-4-7
system:
  file: ../../plugins/agent-plugins/gl-reconciler/agents/gl-reconciler.md
  append: "You are running headless. Produce files in ./out/; do not assume an open Office document."
tools:
  - type: agent_toolset_20260401
    default_config: { enabled: false }
    configs:
      - name: read
        enabled: true
      - name: grep
        enabled: true
      - name: glob
        enabled: true
  - type: mcp_toolset
    mcp_server_name: internal-gl
    default_config: { enabled: true }
  - type: mcp_toolset
    mcp_server_name: subledger
    default_config: { enabled: true }
mcp_servers:
  - type: url
    name: internal-gl
    url: ${GL_MCP_URL}
  - type: url
    name: subledger
    url: ${SUBLEDGER_MCP_URL}
skills:
  - { from_plugin: ../../plugins/agent-plugins/gl-reconciler }
callable_agents:
  - manifest: ./subagents/reader.yaml
  - manifest: ./subagents/critic.yaml
  - manifest: ./subagents/resolver.yaml
```

`pitch-agent/agent.yaml` tools 예: `agent_toolset_20260401` + `mcp_toolset` (`capiq`, `daloopa`).

`reader.yaml` 의 하네스 전용 `output_schema` (API 로 나가지 않음, `test-cookbooks.sh` 가 leak 검사):

```yaml
output_schema:
  type: object
  required: [asset_class, status, breaks]
  additionalProperties: false
  properties:
    asset_class: { type: string, maxLength: 32, pattern: "^[A-Za-z0-9_-]+$" }
    status: { enum: [clean, breaks_found, error] }
    breaks:
      type: array
      maxItems: 500
      items:
        type: object
        required: [account, gl_balance, sub_balance, variance]
        additionalProperties: false
        properties:
          account:        { type: string, maxLength: 64,  pattern: "^[A-Za-z0-9._:-]+$" }
          gl_balance:     { type: number }
          sub_balance:    { type: number }
          variance:       { type: number }
          suspected_cause: { enum: [temporal_cutoff, system_drift, reclass, unknown] }
          evidence_refs:
            type: array
            maxItems: 10
            items: { type: string, maxLength: 256, pattern: "^[A-Za-z0-9 ._/:#-]+$" }
```

`steering-examples.json` 은 POST 바디가 아니다. 쿡북 필수 파일이며 `check.py` 가 JSON 파싱만 한다. `gl-reconciler` 예:

```json
[
  {
    "event": "Reconcile GL vs subledger, trade date 2026-04-30, classes: equities, fixed-income, derivatives",
    "description": "Daily run across three asset classes"
  },
  {
    "event": "Reconcile GL vs subledger, trade date 2026-03-31, classes: all, threshold: 10000",
    "description": "Month-end run with explicit variance threshold"
  },
  {
    "event": "Re-trace break: account 41200-EQ-US, trade date 2026-04-30",
    "description": "Follow-up steering event to deep-dive a single break"
  }
]
```

키는 `event`, `description`. orchestrate 의 `payload.event` 와 같은 역할의 문자열이다.

---

## 11. depth-1 `callable_agents`

`managed-agent-cookbooks/README.md`:

> **Research preview:** `callable_agents` (multi-agent delegation) supports **one delegation level**. An orchestrator can call workers; workers cannot call further subagents.

README.md:

> **Research Preview:** subagent delegation (`callable_agents`) is a preview capability. See per-agent READMEs for security and handoff guidance.

강제 지점:

1. **문서 계약**: 워커 yaml 은 `callable_agents: []` 를 둘 수 있다 (`reader.yaml` 이 그렇게 둔다).
2. **`test-cookbooks.sh`**: 해석된 바디 배열에서 마지막이 아닌 항목이 truthy `callable_agents` 를 가지면 `depth>1 (subagent has callable_agents)`.
3. **`deploy-managed-agent.sh`**: 재귀 깊이 캡이 없다. 워커 yaml 에 `manifest` 가 있으면 그 워커도 POST 되고, 부모의 `callable_agents` 에 `{type:agent,id,version}` 이 들어간다. depth>1 페이로드는 스크립트가 막지 않고 dry-run 테스트가 막는다.
4. **명명된 에이전트 간 호출은 `callable_agents` 가 아니다.** cookbooks README: "Named agents never call each other directly." 그 경로는 `handoff_request` + `orchestrate.py`.

leaf 의 Write 보유는 cookbooks README 표에서 Bold 로만 표시된다. `check.py` / `test-cookbooks.sh` 는 Write 도구를 검사하지 않는다.

GL 보안 티어 (`managed-agent-cookbooks/gl-reconciler/README.md`):

| Tier | Touches untrusted docs? | Tools | Connectors |
|---|---|---|---|
| **`reader`** | **Yes** | `Read`, `Grep` only | None |
| **Orchestrator** | No | `Read`, `Grep`, `Glob`, `Agent` | Read-only GL + subledger MCPs |
| **`resolver`** (Write-holder) | No | `Read`, `Write`, `Edit` | None |

---

## 12. CI

워크플로 파일은 세 개뿐이다.

### 12.1 `plugin-validate.yml`

```yaml
name: plugin-validate
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
env:
  CLAUDE_VERSION: 2.1.143
```

주석:

> Runs the official Claude Code plugin linter over every plugin and the marketplace manifest. Catches malformed manifests (e.g. hooks.json as a bare [] instead of {"hooks": {}}) before they reach users.
>
> 2.1.143: first release whose `plugin validate` accepts `displayName` on marketplace entries (2.1.140 and earlier reject it as an unrecognized key).

잡 `validate`, `ubuntu-latest`.

- checkout `@v4`
- cache `@v4` 경로: `~/.local/bin/claude` 와 `~/.local/share/claude`. 키: `claude-cli-${{ runner.os }}-${{ env.CLAUDE_VERSION }}-v2`. 주석: 심링크만 캐시하면 dangling (exit 127).
- 캐시 미스 시: `curl -fsSL https://claude.ai/install.sh | bash -s "$CLAUDE_VERSION"`
- 검증:

```bash
claude plugin validate .claude-plugin/marketplace.json || fail=1
while IFS= read -r manifest; do
  plugin_dir="$(dirname "$(dirname "$manifest")")"
  claude plugin validate "$plugin_dir" || fail=1
done < <(find plugins -path '*/.claude-plugin/plugin.json' | sort)
```

`fail` 누적 후 하나라도 실패하면 `::error::plugin validation failed — see grouped logs above`, exit 1. `scripts/check.py` 는 이 워크플로에서 호출되지 않는다.

### 12.2 `version-bump.yml`

섹션 9.3. `on: pull_request` 만. `scripts/version_bump.py --check`.

### 12.3 `secret-scan.yml`

```yaml
name: secret-scan
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
```

잡 `gitleaks`, `ubuntu-latest`.

step 1: checkout `actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683` (주석 v4.2.2), `fetch-depth: 0`.

step 2: gitleaks v8.28.0

```bash
curl -sSL -o gitleaks.tgz \
  https://github.com/gitleaks/gitleaks/releases/download/v8.28.0/gitleaks_8.28.0_linux_x64.tar.gz
echo "a65b5253807a68ac0cafa4414031fd740aeb55f54fb7e55f386acb52e6a840eb  gitleaks.tgz" | sha256sum -c -
tar -xzf gitleaks.tgz gitleaks
./gitleaks git --redact --exit-code 1 .
```

step 3: internal-reference scrub

```bash
if grep -rInE '\.ant\.dev|antspace\.dev|anthropic-internal|\bgo/[a-z][a-z0-9_-]+\b' \
    --include='*.md' --include='*.yaml' --include='*.yml' --include='*.json' \
    --include='*.py' --include='*.sh' \
    --exclude-dir=.github . ; then
  echo "::error::internal Anthropic references found above"
  exit 1
fi
```

정규식 네 갈래:

- `\.ant\.dev`
- `antspace\.dev`
- `anthropic-internal`
- `\bgo/[a-z][a-z0-9_-]+\b`

확장자: md, yaml, yml, json, py, sh. `.github` 디렉터리는 제외. 매칭이 하나라도 있으면 실패.

세 워크플로 모두 `permissions.contents: read`. 배포 스크립트·`check.py`·`test-cookbooks.sh` 는 CI yaml 에 없다.

---

## 13. 파일 기반, 빌드 없음

README:

> Everything is file-based — markdown and JSON, no build step.

Contributing:

> Everything here is markdown and YAML. Fork, edit, PR.

`CLAUDE.md` Development Workflow:

> 1. Edit markdown files directly - changes take effect immediately
> 2. Test commands with `/plugin:command-name` syntax
> 3. Skills are invoked automatically when their trigger conditions match

빌드·패키지 매니페스트(package.json, Makefile, pyproject.toml 등)는 이 분석이 읽은 하네스 파일에 없다. 런타임 변환은 배포 시 `deploy-managed-agent.sh` 가 로컬에서 수행한다 (yaml→json, 파일 inline, zip 업로드).

새 콘텐츠 절차 (README):

- 새 스킬 → `plugins/vertical-plugins/<vertical>/skills/` 에 추가 후 `python3 scripts/sync-agent-skills.py`
- 새 에이전트 → `plugins/agent-plugins/<slug>/` (`agents/<slug>.md` + `skills/`) 와 `managed-agent-cookbooks/<slug>/`
- 푸시 전 `python3 scripts/check.py`

`CLAUDE.md` 는 `.ps1` 순수 ASCII 와 `check.py` 의 hooks 자가설치를 같은 워크플로에 묶는다.

---

## 14. 코드 vs 주석 불일치 (있는 것만)

1. `deploy-managed-agent.sh` 헤더: "Reader subagents with an `output_schema` block get a thin validation wrapper". 본문은 `del(.output_schema)` 만 하고 `validate.py` 를 호출하지 않는다.
2. `validate.py` docstring: "the deploy script extracts them". 추출·저장 코드는 deploy 스크립트에 없다.
3. cookbooks README 매핑 표: `callable_agents` version 이 `latest`. 스크립트는 API `.version // 1` (숫자) 을 넣는다. `latest` 는 스킬 객체의 `version` 에만 있다.
4. `check.py` `ASCII_ONLY_SUFFIXES = {".ps1", ".psm1", ".psd1"}` 이지만 루프는 `*.ps1` 만.
5. `check.py` JSON glob / CI `find plugins` 는 `claude-for-msft-365-install/.claude-plugin/plugin.json` 을 파싱·CLI validate 하지 않는다. marketplace source 존재 검사와 `version_bump.py **/.claude-plugin/plugin.json` 은 포함한다.
6. `from_plugin` 은 `head -1` 로 첫 항목만 펼친다. 이후 `from_plugin` 엔트리는 삭제된다.

---

## 15. 정규식 · 엔드포인트 · 스키마 인덱스

```
HANDOFF_RE                 \{"type":\s*"handoff_request".*?\}     (re.DOTALL)
HANDOFF context_ref        ^[A-Za-z0-9 ._/:#-]+$
yaml2json NAME             \$\{([A-Z0-9_]+)\}
yaml2json SAFE             ^[A-Za-z0-9._/:@-]*$
agent.md skill backticks   `([a-z0-9]+(?:-[a-z0-9]+)+)`
secret-scan                \.ant\.dev|antspace\.dev|anthropic-internal|\bgo/[a-z][a-z0-9_-]+\b
reader asset_class         ^[A-Za-z0-9_-]+$
reader account             ^[A-Za-z0-9._:-]+$
reader evidence_refs       ^[A-Za-z0-9 ._/:#-]+$
```

```
POST ${ANTHROPIC_API_BASE:-https://api.anthropic.com}/v1/skills
  headers: x-api-key, anthropic-version: 2023-06-01, anthropic-beta: skills-2025-10-02
  multipart: display_title, files[]=@zip

POST ${ANTHROPIC_API_BASE:-https://api.anthropic.com}/v1/agents
  headers: x-api-key, anthropic-version: 2023-06-01, anthropic-beta: managed-agents-2026-04-01, content-type: application/json

SDK (orchestrate.py): client.beta.agents.sessions.stream(session_id=...)
                      client.beta.agents.sessions.steer(agent_id=..., input=...)
```

`HANDOFF_PAYLOAD_SCHEMA`: object, additionalProperties false, required `event`; `event` string maxLength 2000; `context_ref` string maxLength 256 pattern `^[A-Za-z0-9 ._/:#-]+$`.
