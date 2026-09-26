# claude-for-msft-365-install 분석

출처: `/Users/yeonwoosung/Desktop/financial-services/claude-for-msft-365-install/` 아래 전 파일, 그리고 FSI 관계 확인용으로 상위 `README.md`, `CLAUDE.md`, `.claude-plugin/marketplace.json`, `scripts/check.py`만 인용. 인용 밖 내용은 만들지 않음.

읽은 파일 (플러그인 디렉터리 전부):

- `README.md`
- `.claude-plugin/plugin.json`
- `.claude/skills/verify/SKILL.md`
- `commands/setup.md`, `manifest.md`, `consent.md`, `entra-app.md`, `update-user-attrs.md`, `bootstrap.md`, `access-policies.md`, `debug.md`, `export-data.md`
- `scripts/build-manifest.mjs`, `clear-addin-cache.{sh,ps1}`, `sideload-addin.{sh,ps1}`, `export-addin-data.{sh,ps1}`
- `examples/python-bootstrap/{README.md,app.py,config.py,get_tenant_id.py,mint_dev_token.py,requirements.txt}`

---

## 목적

플러그인 메타데이터:

```json
{
  "name": "claude-for-msft-365-install",
  "description": "Provision direct cloud access (Vertex AI, Bedrock, Azure AI Foundry, or LLM gateway) for the Claude Office add-in. Generates the customized add-in manifest, walks through Azure admin consent, and writes per-user config via Microsoft Graph extension attributes.",
  "version": "0.1.13",
  "author": {
    "name": "Anthropic",
    "email": "support@anthropic.com"
  }
}
```

플러그인 README:

> Admin tooling for configuring the Claude Office add-in to call your own cloud
> (Vertex AI, Bedrock, or an LLM gateway) instead of Anthropic's API.

verify 스킬:

> This plugin is **admin CLI tooling**, not an app. There is nothing to build and
> no server to boot. The surface is the terminal: `scripts/*.sh` on macOS,
> `scripts/*.ps1` on Windows.

setup 커맨드가 말하는 출력:

> You are walking an enterprise admin through configuring the Claude Office add-in
> to call their own cloud instead of Anthropic's API. The output is a customized
> `manifest.xml` they deploy via M365 Admin Center.

경로 표 (`commands/setup.md`):

| Path | What it means | Provisioning | Manifest keys |
|---|---|---|---|
| `gateway` | Add-in → your gateway → (whatever) | None | `gateway_url` (+ `gateway_api_format` if not `/v1/messages`) |
| `vertex` | Add-in → Google Vertex AI, directly | Google OAuth client | `gcp_project_id`, `gcp_region`, `google_client_id`, `google_client_secret` |
| `bedrock` | Add-in → AWS Bedrock, directly | IAM OIDC provider + role | `aws_role_arn`, `aws_region` |
| `foundry` | Add-in → Azure AI Foundry, directly | Foundry resource + API key | `azure_resource_name`, `azure_api_key` |
| `foundry` (keyless) | Add-in → Azure AI Foundry, per-user Entra sign-in | Foundry resource + your Entra app | `azure_resource_name`, `entra_sso=1`, `graph_client_id`, `entra_scope=https://cognitiveservices.azure.com/.default`, `gateway_auth_source=entra` |

gateway를 먼저 묻는 이유 (`setup.md`):

> **do you already run an LLM gateway (LiteLLM, Portkey, Kong, etc.)?**
>
> - **Yes → `gateway`.** Even if the gateway routes to Vertex or Bedrock under
>   the hood — the add-in talks to *your gateway*, not to Google or AWS.

설치 (`README.md`):

```bash
claude plugin marketplace add anthropics/financial-services
claude plugin install claude-for-msft-365-install@claude-for-financial-services
```

Then inside the session: `/claude-for-msft-365-install:setup`

마켓플레이스 등록 (`financial-services/.claude-plugin/marketplace.json`):

```json
{
  "name": "claude-for-msft-365-install",
  "displayName": "Claude for Microsoft 365 Install",
  "source": "./claude-for-msft-365-install",
  "description": "Provision direct cloud access (Vertex AI, Bedrock, or LLM gateway) for the Claude Microsoft 365 add-in. Generates the customized manifest, walks through Azure admin consent, and writes per-user config via Graph extension attributes."
}
```

`plugin.json`은 Foundry를 포함, marketplace description은 Vertex/Bedrock/gateway만 적음.

---

## 관리자 워크플로 커맨드

README가 나열하는 slash command:

| Command | What it does |
|---|---|
| `/claude-for-msft-365-install:setup` | Interactive wizard — provisions cloud resources, admin consent, writes manifest |
| `/claude-for-msft-365-install:manifest` | Generate the customized add-in manifest XML |
| `/claude-for-msft-365-install:consent` | Azure admin consent URL for the add-in's app registration |
| `/claude-for-msft-365-install:update-user-attrs` | Write per-user config via Microsoft Graph extension attributes |
| `/claude-for-msft-365-install:bootstrap` | Build the bootstrap endpoint — per-user MCP servers, skills, dynamic config |
| `/claude-for-msft-365-install:debug` | Diagnose deployment issues — stale config, connect failures, missing add-in |
| `/claude-for-msft-365-install:export-data` | Export a copy of a user's chat history, skills, and MCP registrations |

`commands/`에는 README 표에 없는 두 파일이 더 있다: `access-policies.md`, `entra-app.md`. 둘 다 다른 커맨드가 링크한다.

### `/setup` — 마법사

로그 파일: `~/Desktop/claude-for-msft-365-install-setup.md`

단계 (`setup.md` 목차 그대로):

1. **How does the add-in reach Claude?** — gateway / vertex / bedrock / foundry
1b. **Which Office apps?** — Excel/Word/PowerPoint, Outlook, or both. Outlook은 별도 매니페스트. **Bedrock is not currently supported for Outlook.**
2. **Azure admin consent** — `entra_sso=1`일 때만 (`Bedrock` 또는 per-user config)
3. **org-wide vs per-user**
4. **Generate the manifest** — `build-manifest.mjs` + `office-addin-manifest validate`
5. **Per-user config** — 문자열이면 extension attrs, 구조화 JSON이면 bootstrap
6. **Verify a model is reachable** — Sonnet 4.5 또는 Opus 4.5 (or newer)
7. **Deploy** — M365 Admin Center → Upload custom apps → Office Add-in

배포 URL: `https://admin.cloud.microsoft/?#/Settings/IntegratedApps`

> Propagation to users takes up to 24 hours (usually much faster). The add-in
> appears under **Home → Add-ins** in Excel/Word/PowerPoint once it lands.

### `/consent` — Anthropic 기본 앱만

> **Only needed when `entra_sso=1`** in the manifest. Gateway and Vertex setups
> with org-wide config don't use Entra and can skip this. If you set
> `graph_client_id` (your own Entra app), this page doesn't apply either — you
> manage consent on your app directly.

기본 앱 ID: `c2995f31-11e7-4882-b7a7-ef9def0a0266`

SSO consent URL:

```
https://login.microsoftonline.com/organizations/adminconsent?client_id=c2995f31-11e7-4882-b7a7-ef9def0a0266&redirect_uri=https://pivot.claude.ai/auth/callback
```

Outlook Graph consent (별도, `entra_sso`와 무관):

```
https://login.microsoftonline.com/organizations/v2.0/adminconsent?client_id=c2995f31-11e7-4882-b7a7-ef9def0a0266&scope=https://graph.microsoft.com/Mail.ReadWrite%20https://graph.microsoft.com/Calendars.Read%20https://graph.microsoft.com/People.Read%20https://graph.microsoft.com/User.Read%20offline_access&redirect_uri=https://pivot.claude.ai/auth/callback
```

> The Graph token stays in the user's Outlook client and is never sent to the gateway or to Anthropic

검증: `az ad sp show --id c2995f31-11e7-4882-b7a7-ef9def0a0266`

### `/entra-app` — 자체 Entra 앱

자체 앱이 필요한 매니페스트 키:

| Manifest key | Why your own app |
|---|---|
| `graph_client_id` (Outlook) | Graph permissions are consented against your app, not Anthropic's |
| `entra_scope` | Access token must be audienced to *your* API resource |
| `gateway_auth_source=entra` | Your gateway — or a Foundry resource — validates a token audienced to that resource |
| `graph_cloud` ≠ `global` | Anthropic's app exists only in the commercial cloud |

Redirect URI (둘 다 SPA platform):

- `brk-multihub://pivot.claude.ai` — NAA broker (desktop Office, Outlook web). 없으면 `AADSTS50011`
- `https://pivot.claude.ai/msal-redirect.html` — SPA fallback (Office for the web)

권한 행:

- Outlook Graph: Delegated `Mail.ReadWrite`, `Calendars.Read`, `People.Read`, `User.Read`, `offline_access`
- Gateway/bootstrap: Expose API `api://<app-guid>`, scope 예 `access_as_user`
- Foundry keyless: Azure Cognitive Services Delegated `user_impersonation`, `entra_scope=https://cognitiveservices.azure.com/.default`, 사용자에게 **Cognitive Services User** 역할
- Bedrock WIF: API permission 불필요 — ID token이 web identity

`Expose an API`를 쓴 경우 앱 매니페스트에 `"accessTokenAcceptedVersion": 2`.

백엔드가 검사할 클레임 (`entra_scope` / `gateway_auth_source=entra`):

| Claim | Expected |
|---|---|
| `iss` | `https://login.microsoftonline.com/<tenant-id>/v2.0` |
| `aud` | your Application ID URI (`api://<app-guid>`) |
| `scp` | the scope(s) you exposed, space-separated |
| JWKS | `https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys` |

주권 클라우드: 등록은 `portal.azure.us` / `portal.azure.cn`. Redirect URI는 동일. 매니페스트에 `graph_cloud=us-gov-high` | `us-gov-dod` | `china`.

### `/debug`

증상 라우팅: stale config / Connection failed / add-in not visible / sideload / consent loop / browser console.

캐시 두 층:

| Layer | Who holds it | TTL | How to clear |
|---|---|---|---|
| Service | M365 Admin Center → Exchange Online → client | Up to **72h** for updates (24h for fresh deploys) | Wait, or redeploy with a fresh `<Id>` |
| Client | Office app's Wef folder on each machine | Until app restart, sometimes longer | Clear the cached manifests |

스크립트는 `office-addin-dev-settings`를 쓰지 않는다:

> they do **not** shell out to `office-addin-dev-settings` (its removal path has burned us on customer calls)

macOS 클리어: `Documents/wef`의 `<addin-id>.manifest-*.xml`만. Windows 클리어: `HKCU:\SOFTWARE\Microsoft\Office\16.0\Wef\Developer` 레지스트리만. 중앙 배포 캐시 `%LOCALAPPDATA%\Microsoft\Office\16.0\Wef\<guid>\…`는 건드리지 않음.

> ⚠️ **On Windows that wipe is destructive.** The add-in's chat history,
> skills, MCP registrations, and memory live *inside* the same tree
> (`%LOCALAPPDATA%\Microsoft\Office\16.0\Wef\webview2\…`)

Sideload는 dry-run 없음 (additive/idempotent). 제거는 `clear-addin-cache --id <GUID> --apply`.

---

## 매니페스트 생성

`scripts/build-manifest.mjs`:

> Fetches the canonical add-in manifest and writes a customized copy with your
> org's config baked into the taskpane URL: sensitive settings after #, other settings after ?.

Usage: `node build-manifest.mjs <office|outlook> <out.xml> key=value [key=value ...]`

| Host arg | Apps | Template |
|---|---|---|
| `office` | Excel, Word, PowerPoint | `pivot.claude.ai/manifest.xml` |
| `outlook` | Outlook (mail + calendar) | `pivot.claude.ai/manifest-outlook-3p.xml` |

Outlook은 `MailApp` 스키마, Office는 `TaskPaneApp`. 호스트당 파일 하나.

민감 키 (`SENSITIVE_KEYS`)는 fragment(`#`)로:

```
gateway_token, azure_api_key, google_client_secret, otlp_headers, inference_headers, mcp_servers
```

나머지는 query(`?`). XML의 `&`는 `&amp;`로 이스케이프.

클라우드별 키 (`manifest.md`):

| Cloud | Keys |
|---|---|
| Vertex | `gcp_project_id` `gcp_region` `google_client_id` `google_client_secret` |
| Bedrock | `aws_role_arn` `aws_region` |
| Foundry | `azure_resource_name` `azure_api_key` — or keyless: `azure_resource_name` + Entra |
| Gateway | `gateway_url` `gateway_token` `gateway_auth_header` `gateway_api_format` |
| Gateway (`gateway_api_format=vertex`) | also `gcp_project_id` `gcp_region` |

스크립트가 **hard fail**하는 조합:

- unknown key
- empty value
- `outlook` + `aws_*`
- `aws_role_arn` / `graph_client_id` / `entra_scope` / `gateway_auth_source` 인데 `entra_sso≠1`
- `entra_scope` 있는데 `graph_client_id` 없음
- `gateway_auth_source` 있는데 `entra_scope` 없음
- `graph_cloud`가 `global`이 아닌데 `graph_client_id` 없음

shape 불일치는 warn만. `access_policies` / `available_models`는 JSON 파싱 실패 시 throw.

`graph_cloud` enum: `global` | `us-gov-high` | `us-gov-dod` | `china`. DoD는 항상 명시 필요 (GCC High와 authority host 공유, auto-detect가 GCC High를 고름).

Entra SSO (`entra_sso=1`):

> Set it when your deployment needs the user's Microsoft identity — Bedrock uses it as
> the STS web identity, the bootstrap endpoint uses it as Bearer auth, and
> per-user attrs ride inside it as `extn.*` claims.

기본 `aud`는 Anthropic 앱 GUID `c2995f31-…`. 자체 앱이면 `graph_client_id`. 액세스 토큰이 필요하면 `entra_scope=api://<guid>/<scope>`. `entra_scope`와 `graph_client_id`는 **매니페스트 전용** — extension attr/bootstrap으로 전달 불가 (NAA 초기화 전에 필요).

`gateway_auth_source=entra`: 게이트웨이 호출에 Entra access token을 `Authorization: Bearer`로 보냄. `gateway_token`은 무시되고 warn.

Foundry keyless: `entra_scope=https://cognitiveservices.azure.com/.default`. `ai.azure.com`이 아님 — NAA delegated `user_impersonation`의 audience.

기타 키:

- `bootstrap_url` — 시작 시 per-user JSON
- `mcp_servers` — JSON array `{url, label, headers?, discover?}`, `{{gateway_token}}` 보간
- `otlp_endpoint` / `otlp_headers` / `otlp_resource_attributes` — OTLP/HTTP only, gRPC 없음, `/v1/traces` append
- `inference_headers` — 게이트웨이에만. 예약 헤더 (`Authorization`, `x-api-key`, `Content-Type`, `Host`, `Content-Length`, `User-Agent`, `Cookie`, `anthropic-*` / `x-amz-*` / `x-goog-*`) drop
- `auto_connect` — 기본 자동 연결, `0`이면 폼
- `allow_1p` — enterprise 키가 있으면 기본 `0` (Claude.ai Back 버튼 숨김)
- `disabled_features` — comma list
- `available_models` — picker **override** (retired `disabled_models` / `additional_models` 대체)
- `access_policies` — IAM-shaped JSON array. Entra extension attr에 안 들어감 (256자)

`disabled_features` slug (`manifest.md`):

| Slug | Effect |
|---|---|
| `skills.authoring` | Blocks creating, editing, and uploading skills … Running admin-provisioned skills is unaffected. |
| `thumbs` | Blocks response feedback |
| `addin.access` | Kill switch — the add-in refuses to run |
| `file.upload` | Blocks attaching files |
| `web_search` | Removes the native web_search and web_fetch server tools … Pair with `mcp_servers` to substitute your own in-network search tool |

버전: M365 Admin Center는 `<Id>` + `<Version>`으로 캐시. 같은 버전 재업로드는 silently ignored. 네 번째 세그먼트 bump.

검증: `npx --yes office-addin-manifest validate manifest.xml`

"An add-in with this ID already exists" → `<Id>`를 새 UUID로. 템플릿이 marketplace install ID를 가짐.

URL 슬롯 (`build-manifest.mjs`): `<SourceLocation DefaultValue="...">`와 `id="Taskpane.Url"` 전부 (`/g`). Outlook MailApp이 V1_0/V1_1에 Taskpane.Url을 반복.

---

## Graph 확장 특성

`commands/update-user-attrs.md`:

> The attributes are already registered on Anthropic's app (`c2995f31-…`) — you
> don't create schema, you just write values. The add-in reads
> `extension_c2995f3111e74882b7a7ef9def0a0266_<key>` from the user's ID token.

> **Requires `entra_sso=1` in the manifest.** Without it the add-in never
> acquires an Entra token, so these attributes are never read — they silently do
> nothing.

> The add-in merges per-user attrs over manifest params, so whatever's here wins. All values are 256 chars max.

문서가 예시로 든 키: `gateway_token`, `gateway_url`, `gateway_api_format`, `inference_headers`, `bootstrap_url`, `gcp_project_id`, `gcp_region`, `google_client_id`, `google_client_secret`, `aws_role_arn`, `aws_region`, `otlp_endpoint`, `otlp_headers`, `otlp_resource_attributes`.

단일 사용자:

```bash
az rest --method PATCH \
  --uri "https://graph.microsoft.com/v1.0/users/<upn>" \
  --body '{"extension_c2995f3111e74882b7a7ef9def0a0266_<key>":"<value>"}'
```

성공은 204 empty. Graph 읽기는 write와 immediately consistent. 애드인이 읽는 쪽은 STS 토큰 캐시 **최대 1시간**. Office 앱을 완전히 종료해야 새 NAA 토큰.

벌크: `users.csv` (첫 열 UPN, 빈 셀은 skip). macOS는 `apply.sh` (`read -a`는 bash-only), Windows는 `apply.ps1`. 시크릿이 채팅/히스토리에 안 들어가게 CSV 경로를 권장.

권한: 403이면 `az login`에 `User.ReadWrite.All` 없음.

`access_policies`는 여기 못 씀:

> `access_policies` is manifest / bootstrap only — it does **not** fit in Entra
> extension attributes (256-char cap).

---

## Python bootstrap

`commands/bootstrap.md`:

> You host an HTTPS GET handler. The add-in calls it at startup with the user's
> Entra token, you return per-user JSON, the response overrides manifest and
> extension attrs for that user. This is how you push structured config —
> `mcp_servers`, `skills` — that flat string attrs can't carry.

설정 계층 (나중 것이 이김): **manifest params → extension attrs → bootstrap response**.

`{{key}}` 보간:

1. `bootstrap_url` 자체는 manifest + attrs만
2. 응답 필드는 전체 merge (응답 안의 값도)

미해석 `{{key}}`는 그대로 남김.

CORS — 모든 URL:

> The add-in is a browser. Every fetch — `bootstrap_url`, every
> `mcp_servers[].url`, every `skills[].url` — happens browser-side from inside
> the Office taskpane. Without `Access-Control-Allow-Origin:
> https://pivot.claude.ai` on the response, the browser blocks it

권장 preflight:

```
Access-Control-Allow-Origin:  https://pivot.claude.ai
Access-Control-Allow-Methods: GET
Access-Control-Allow-Headers: Authorization, X-Claude-User-Agent, *
```

skills URL은 버킷 CORS가 필요 (presigned URL은 CORS를 주지 않음). S3 / GCS / Azure 예시가 문서에 있음. `otlp_endpoint`도 collector CORS.

요청:

```
GET <bootstrap_url>
Authorization: Bearer <entra_token>            # only if entra_sso=1
X-Claude-User-Agent: claude-<app>/<version>    # always sent
```

`<app>` = `word` | `excel` | `powerpoint`.

`entra_sso=1`일 때 JWT 검사:

| Claim | Check |
|---|---|
| `aud` | `c2995f31-11e7-4882-b7a7-ef9def0a0266` — 기본 앱, 또는 `graph_client_id`면 그 GUID |
| `iss` | `https://login.microsoftonline.com/<YOUR_TENANT_ID>/v2.0` |
| `exp` | Not expired |
| `oid` | 사용자 lookup 키 (email은 바뀔 수 있음) |

`entra_scope`가 있으면 Bearer는 **access token**. `aud` = Application ID URI, `scp` 확인.

응답: `200`, `application/json`, CORS. flat object, 모든 필드 optional. unknown key는 ignore.

필드: provider 키들, `otlp_*`, `inference_headers`, `mcp_servers`, `skills` (`content` base64 또는 `url` presigned; zip 또는 raw `SKILL.md` sniff), `disabled_features` (JSON array), `available_models`, `access_policies` (native array, 문자열 아님), `bootstrap_expires_at` (초/밀리초 auto-detect).

### 레퍼런스 구현 `examples/python-bootstrap/`

`requirements.txt`: `fastapi`, `uvicorn`, `PyJWT[crypto]`

`config.py` — 여기만 고치라고 README가 말함.

- `AUDIENCE = "c2995f31-11e7-4882-b7a7-ef9def0a0266"`
- `ISSUER` / `JWKS_URL` from `TENANT_ID`
- `DEV_JWKS_PATH`는 `HOST==127.0.0.1`일 때만. 아니면 `SystemExit`
- 카탈로그 예시 스킬: `deal-memo` (S3 zip URL), `compliance-check` (inline base64 SKILL.md), `risk-dashboard`
- MCP 예시: Linear SSE, internal risk API with `Authorization: Bearer {{gateway_token}}`
- `RULES` first-match. `when` 키: `group` (token `groups` claim), `user` (`oid`), `app` (`word`|`excel`|`powerpoint`)
- 기본 룰: `{"when": {}, "skills": ["compliance-check"], "mcp_servers": []}`
- IB 예시: `{"when": {"app": "word", "group": "investment-banking"}, "skills": ["deal-memo", "compliance-check"], "mcp_servers": ["linear"]}`

`app.py`: `GET /bootstrap` → validate JWT RS256 → `oid` + `groups` + UA에서 app → `resolve()` → `{skills, mcp_servers, bootstrap_expires_at: now+3600}`. CORS origin `https://pivot.claude.ai`.

`get_tenant_id.py`: 이메일/도메인 → OIDC well-known `issuer`, 또는 `az account show`.

`mint_dev_token.py`: self-signed RSA, `aud`는 기본 앱 ID, `groups`/`oid` CLI 인자. `dev_private.pem` + `dev_jwks.json` 생성.

README: `groups` claim은 기본이 아님 — *App registration → Token configuration → Add groups claim*.

보안 문구 (`bootstrap.md`):

> JWT validation is the security boundary. … A handler that skips this and trusts
> `preferred_username` from an unverified token is an open endpoint with extra steps.

---

## PowerShell ASCII / BOM

verify 스킬:

> **`.ps1` files must be pure ASCII** (enforced by `scripts/check.py`).
> Windows PowerShell 5.1 reads a BOM-less `.ps1` as ANSI, so an em dash decodes
> to mojibake containing `"`, which terminates a string and breaks the parse.
> `clear-addin-cache.ps1` shipped broken this way and no macOS check caught it.

> **Never claim the `.ps1` scripts work without running them on Windows.**
> macOS has no PowerShell, so a `.ps1` change verified only here is unverified.
> Run it on a real Windows host against Windows PowerShell 5.1

권장 parse check:

```powershell
$e = $null
[System.Management.Automation.PSParser]::Tokenize(
  (Get-Content -Raw .\clear-addin-cache.ps1), [ref]$e) | Out-Null
if ($e.Count) { $e | ForEach-Object { $_.Message } } else { 'parse ok' }
```

상위 리포 `CLAUDE.md`:

> **Keep `.ps1` files pure ASCII.** Windows PowerShell 5.1 — still the default shell on managed Windows — decodes a BOM-less `.ps1` using the machine's ANSI code page, not UTF-8. An em dash or curly quote becomes mojibake that can contain a literal `"`, which terminates a string and makes the whole script fail to *parse*. Write `--`, not `—`. This is invisible on macOS and fatal on Windows; `check.py` gates it.

`scripts/check.py` 게이트 (리포 루트, 플러그인 디렉터리가 아님):

```python
# --- 6. PowerShell scripts must be pure ASCII -------------------------------
ASCII_ONLY_SUFFIXES = {".ps1", ".psm1", ".psd1"}
for ps in sorted(ROOT.rglob("*.ps1")):
    ...
    raw = ps.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        continue  # an explicit BOM tells PS 5.1 it is UTF-8; then non-ASCII is fine
    for lineno, line in enumerate(raw.split(b"\n"), 1):
        bad = sorted({b for b in line if b > 0x7F})
        if bad:
            err(
                f"non-ascii: {rel(ps)}:{lineno}: byte(s) {chars} in a .ps1 with no "
                f"UTF-8 BOM -- Windows PowerShell 5.1 will mis-decode this and may "
                f"fail to parse the file. Use ASCII (-- for an em dash) or add a BOM."
            )
```

이 플러그인의 `.ps1` 세 개 (`clear-addin-cache.ps1`, `sideload-addin.ps1`, `export-addin-data.ps1`)는 ASCII 주석/식별자를 씀. em dash 대신 `--`. comment-based help는 `.SYNOPSIS` / `.DESCRIPTION` / `.EXAMPLE`.

Windows 스크립트 동작 요약:

- `clear-addin-cache.ps1`: `-Id` / `-Manifest` / `-Apply`. 기본 dry-run. GUID regex 강제 (`*` wildcard blast 방지). `Remove-ItemProperty -Name`에 `[WildcardPattern]::Escape` (경로가 character class로 파싱되는 것 방지). miss면 exit 1 ("already clear"로 오해 → Wef wipe 방지).
- `sideload-addin.ps1`: `HKCU:\SOFTWARE\Microsoft\Office\16.0\Wef\Developer`에 값 이름=`<Id>`, 데이터=절대 매니페스트 경로. `office-addin-dev-settings` 미사용.
- `export-addin-data.ps1`: `%LOCALAPPDATA%\Microsoft\Office\16.0\Wef\webview2`. IndexedDB는 Claude DB 이름 바이트 검색 (`claude-chat-history` 등, ASCII + UTF-16LE). localStorage는 프로필 전체 복사. `-IncludeAll`은 인식 실패 시. Office가 열려 있으면 warn (원본은 안 건드림). 빈 export는 exit 1.

macOS 대응:

- `clear-addin-cache.sh`: `shopt -s nocaseglob` (Office가 매니페스트 `<Id>` 케이싱으로 파일명 씀). APPS=`Excel Word Powerpoint Outlook`. `--id`에 `[ $# -ge 2 ]` 가드 (`set -e` + `shift 2`가 무출력 exit 1 되는 것 방지).
- `sideload-addin.sh`: Excel/Word/Powerpoint만 (Outlook 없음). `$HOME/Library/Containers/com.microsoft.$app/Data/Documents/wef/<Id>.manifest.xml` 복사.
- `export-addin-data.sh`: WebKit WebsiteData, origin 파일 바이너리 파싱 (scheme/host/port), sqlite3 `.backup`. DB 이름: `claude-chat-history`, `claude-local-skills`, `claude-mcp-gateways`, `claude-memory`, `claude-office-snipped-results`. 토큰은 export 안 함.

데이터 키:

> Storage is keyed by the origin the add-in is served from, not by add-in ID

macOS: manifest=`Data/Documents/wef`, storage=`Data/Library/WebKit/WebsiteData`. Windows: 둘 다 Wef 아래 — 그래서 폴더 wipe가 대화를 지움.

---

## Access policies

`commands/access-policies.md`:

> `access_policies` is the add-in's access-control mechanism going forward: a JSON
> list of allow/deny **statements** — IAM-shaped — that decide which
> features are available and under what conditions.

`disabled_features`는 전원 on/off. `access_policies`는 같은 스위치 + 조건 + effect.

오늘 문서가 말하는 두 document-conditioned control:

- `addin.access` — 열린 문서에서 애드인 실행 여부. 라벨 또는 path.
- `file.upload` — 첨부 파일의 **그 파일** 라벨 (Office files and PDFs).

문법:

```
statement   := { effect, action, resource? }
effect      := "allow" | "deny"
action      := <slug> | [ <slug>, ... ]
resource    := { type, identifiers: [identifier, ...], description? }
type        := "open_file" | "uploaded_file"
identifier  := { type: "mip_label_guid" | "mip_label_name" | "file_path", <one operator> }
```

action slug:

| `action` slug | Gates | Takes a `resource`? |
|---|---|---|
| `addin.access` | Whether the add-in runs at all on the open document | `open_file` |
| `file.upload` | Whether a file may be attached | `uploaded_file` |
| `skills.authoring` | Creating, editing, and uploading skills; running admin-provisioned skills is unaffected | — |
| `thumbs` | Response feedback | — |

Unknown slug는 skip + report. resource 없는 statement는 모든 slug에 동작.

연산자: `equals` / `startsWith` / `endsWith` / `exists`. 식별자당 정확히 하나.

- `mip_label_guid`: `equals` | `exists` only
- `mip_label_name`: 전부
- `file_path`: `equals` | `startsWith`

매칭 규칙: statements OR, identifiers OR, matching `deny` beats matching `allow`. 어떤 `(action, resource type)`에 대한 첫 `allow`가 그 스코프를 default-deny로 뒤집음. `description`은 UI/telemetry용, 매칭 안 함.

라벨 GUID 수집:

```powershell
Connect-IPPSSession -UserPrincipalName admin@theirtenant.com
Get-Label | Sort-Object Priority | Format-Table Priority, DisplayName, Name, Guid, ParentId
```

또는 Purview portal URL, Graph `GET /security/informationProtection/sensitivityLabels`.

설명하라고 하는 여섯 가지:

1. statement는 적힌 것만 — `addin.access`가 upload를 막지 않음. 둘 다 막으려면 두 statement.
2. parent label GUID는 파일 안에 없음. sublabel GUID 또는 `"Parent - Sublabel"` `startsWith`.
3. `mip_label_name`은 exact, case-sensitive, locale, rename에 깨짐. GUID 선호.
4. 읽을 수 없는 라벨은 fail closed (`uploaded_file` statement가 있을 때). Purview-encrypted, legacy `.xls`/`.ppt`/`.doc`.
5. unlabeled: `{ "type": "mip_label_guid", "exists": false }`. `uploaded_file`에서는 이미지/CSV/plain text도 매칭.
6. `file_path`는 Office가 보고하는 그대로. ASCII case-fold, `\`=`/`, `file:` URL은 path. prefix는 separator로 끝낼 것. alias 미해석. SharePoint/OneDrive는 percent-encoded. unsaved는 deny 미매칭, allow-list에서는 거부. upload에는 path 없음. 옛 빌드는 `file_path` 포함 statement를 drop → 라벨 규칙과 분리해서 쓸 것.

`build-manifest.mjs`는 JSON이 아니면 reject, grammar 경고. 런타임은 문법 실패 statement를 silently drop — 빌드 타임이 유일한 catch.

매니페스트 키로 넘김. bootstrap에서는 native JSON array.

---

## FSI 에이전트와의 관계

상위 `CLAUDE.md`:

> `claude-for-msft-365-install/`     # admin tooling for the Microsoft 365 add-in (separate from FSI plugins)

상위 `README.md` 섹션 **Claude for Microsoft 365 — Install Tooling**:

> If your firm runs Claude inside Excel, PowerPoint, Word, and Outlook via the Microsoft 365 add-in, [`claude-for-msft-365-install/`](./claude-for-msft-365-install) is the admin tooling to provision it against **your own cloud** — Vertex AI, Bedrock, or an internal LLM gateway — instead of Anthropic's API.
>
> It's a Claude Code plugin (not a Cowork plugin) that walks an IT admin through generating the customized add-in manifest, granting Azure admin consent, and writing per-user routing config via Microsoft Graph.
>
> This is separate from the agents and vertical plugins above — it's the on-ramp that gets the add-in deployed in a tenant, after which the agents and skills here are what runs inside it.

같은 마켓플레이스 `claude-for-financial-services`에 등록됨 (`marketplace.json` 마지막 플러그인). 에이전트/버티컬(`plugins/agent-plugins/`, `plugins/vertical-plugins/`, `managed-agent-cookbooks/`)과 디렉터리·역할이 다름.

연결 지점 (플러그인 문서가 말하는 것):

1. **배포 온램프** — 테넌트에 애드인을 Vertex/Bedrock/Foundry/gateway로 붙인 뒤, FSI agents/skills가 그 안에서 돈다 (`README.md` 위 인용).
2. **bootstrap `skills` / `mcp_servers`** — per-user로 스킬 zip/`SKILL.md`와 MCP를 주입. python-bootstrap 예시 카탈로그가 FSI 워크플로 이름: `deal-memo`, `compliance-check`, `risk-dashboard`; 룰 그룹 `investment-banking`, `risk`.
3. **`disabled_features` / `access_policies`** — `skills.authoring`은 사용자 작성만 막고 admin-provisioned skills는 그대로. Purview 라벨로 기밀 문서에서 애드인 자체를 끔.
4. **검증은 리포 루트 `scripts/check.py`** — FSI 매니페스트 린트와 같은 게이트가 `.ps1` ASCII도 검사.

이 플러그인 디렉터리 안에는 FSI agent.yaml / skill 소스가 없다. 에이전트 코드는 `plugins/` 쪽.

---

## 검증 스킬

`.claude/skills/verify/SKILL.md` — 이 플러그인 변경을 fake `$HOME`으로 돌리는 방법.

- lint: 리포 루트 `python3 scripts/check.py`, `bash -n` on `.sh`
- fake HOME sandbox: Excel/Word/Powerpoint `Documents/wef`에 심은 매니페스트. **two IDs across two apps**, mixed case (cross-app blast, case-sensitive glob 버그를 잡은 적 있음)
- storage 보존 증명: `WebsiteData` vs `wef` snapshot-diff. "The load-bearing claim of this plugin is that clearing a manifest never touches the user's chat history."
- IndexedDB 검증: `PRAGMA integrity_check` / `SELECT count(*)`는 `no such collation sequence: IDBKEY` — 손상 아님. `SELECT sum(length(value)) FROM Records;`
- Bash tool은 zsh — bash-only (`shopt`, glob)는 `bash <<'EOF'`
- arg parser: `--flag`가 마지막이면 `shift 2`가 `set -e`에서 무출력 실패. 각 flag에 `[ $# -ge 2 ]`
