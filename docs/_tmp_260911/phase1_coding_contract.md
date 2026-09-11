# Phase 1 coding-agent contract

Do not copy Claude Code prompts. Use NEOS wording only.

## File ownership (do not cross)

| Owner | Files |
|---|---|
| Prompt (already landed or landing in parallel) | `neos/coding/prompts/**`, `neos/coding/runtime.py` (`system=` only), `tests/coding/prompts/**` |
| Registry agent | `neos/coding/tools/registry.py`, `tests/coding/tools/test_registry.py` |
| Executor agent | `neos/coding/tools/executor.py`, `tests/coding/tools/test_executor.py` |
| Shared (main already updates) | `neos/coding/sandbox/observability.py` |

## Registry

### `read_file.v1` schema
```
path: str
offset: int = 1   # 1-based line, ge=1
limit: int | None = None  # ge=1, le=5000; None = all lines (still preview-capped)
```
Validate extra=forbid. Normalize `path` with `normalize_workspace_path`.
Existing test that compared `call.input == {"path": ...}` must include defaults.

### `edit_file.v1` (NEW)
```
path: str
old_string: str
new_string: str
replace_all: bool = False
```
Risk: `ToolRisk.WORKSPACE_WRITE`. Path uses `ensure_mutable_workspace_path` (same as write).
Place it in `_TOOL_SPECS` immediately before `write_file.v1`.
Definitions order becomes:
list_tree, stat, read_file, search_text, git_status, git_diff, git_log, **edit_file**, write_file, execute.

### Descriptions (required phrases)

Each description: one-line purpose + when to use + when not + what to do on policy denial.

- `list_tree.v1`: list a directory. Do not use this to read file contents (`read_file.v1`).
- `stat.v1`: metadata only. Prefer this over reading a whole file just to see size.
- `read_file.v1`: read workspace file. Use `offset`/`limit` for large files. Existing files must be read before `edit_file.v1` or `write_file.v1`.
- `search_text.v1`: search workspace text. **Do not use `execute.v1` with rg/grep/find.**
- `git_status.v1` / `git_diff.v1` / `git_log.v1`: prefer these over `execute.v1` git.
- `edit_file.v1`: exact string replace. `old_string` must be unique unless `replace_all`. Read first. Prefer edit over write for existing files.
- `write_file.v1`: create or replace entire file. Existing files require a prior `read_file.v1` in this sandbox. Prefer `edit_file.v1` for partial edits. Do not add unrequested README/docs.
- `execute.v1`: argv only. No `sh|bash|zsh -c`. No network clients. No package install. git via execute is status/diff/log only. Prefer dedicated tools. On `policy_*` denial, do not retry the same argv.

A registry test must assert `search_text.v1` description mentions `execute.v1` and `rg` or `grep`, and `execute.v1` description mentions `-c` / network / git.

## Executor

### Read
1. `session.read_file(path)` whole bytes.
2. Decode utf-8 with `errors="replace"`.
3. Split into lines with `splitlines(keepends=True)`.
4. Slice `[offset-1 : offset-1+limit]` (limit None → rest).
5. Prefix each line with 1-based number: `{n:>6}|` + line text (keep original newlines).
6. Then apply existing `_bounded_bytes` preview cap on the numbered text encoded utf-8.
7. `original_bytes` = original file byte length.
8. `truncated` if line slice omitted lines OR preview cap truncated.
9. Record path as read for this `session.sandbox_id` (only on successful `read_file.v1`, not internal reads).

### Write pre-read
- Existence via `session.stat(path)`. `SandboxNotFound` / `FileNotFoundError` → new file, write allowed.
- Existing file without a prior successful `read_file.v1` on same sandbox+normalized path → `denied` / `precondition_read_required`. Do **not** write.
- Internal stat must NOT mark the path as read.

### Edit
1. Same pre-read rule as write (`precondition_read_required`).
2. Read file bytes. Missing → `sandbox_not_found`.
3. Decode utf-8 **strict**. Failure → `denied` / `edit_not_text`.
4. `count = text.count(old_string)`.
   - 0 → `denied` / `edit_old_string_not_found`
   - >1 and not `replace_all` → `denied` / `edit_old_string_not_unique`
5. Replace (`replace` or `replace(..., 1)` if not replace_all) and `write_file`.
6. Return `ToolResult.ok` with new revision.

### FakeSession tests
- Update `call()` helper so `edit_file.v1` is WORKSPACE_WRITE.
- Existing write dispatch test must either `read_file` first or make `stat` raise FileNotFoundError for new files. Prefer: FakeSession.files dict; `stat`/`read_file` raise FileNotFoundError when missing; `write_file` creates. Then current write-without-read of unknown path still works if FakeSession starts empty — **but current FakeSession.stat always succeeds**. Change FakeSession so `stat`/`read_file` succeed only if `path in files` (seed `files` for read tests). Update existing read tests to seed `files["a.txt"] = b"abcdef"`.

Keep other existing executor tests green.

## Out of scope
Parallel RO, compact, todo_write, hooks, Claude prompt paste, LangGraph, chat skills.
