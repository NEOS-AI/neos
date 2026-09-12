# Phase 3 remote-console contract

Do not replace ChannelGateway with a Hermes runtime. Route on top of Phase 0 gates.

## File ownership

| Owner | Files |
|---|---|
| Core (landed / landing) | `neos/api/channels/session_key.py`, `commands.py`, `inflight.py`, `gateway.py`, `neos/config/schema.py` ChannelConfig fields, `settings.py` exact paths, `tests/api/channels/test_session_key.py`, `test_commands.py`, `test_inflight.py`, `test_gateway_router.py` |
| Slack | `adapters/slack.py`, `tests/api/channels/test_slack_adapter.py` |
| Discord | `adapters/discord.py`, `tests/api/channels/test_discord_adapter.py` |
| Telegram | `adapters/telegram.py`, `tests/api/channels/test_telegram_adapter.py` |

## Session key v2

`build_session_key(channel, scope, chat, thread="-") -> str`

Format: `v2:{channel}:{scope}:{chat}:{thread}`

- Replace `:` in each part with `_`.
- Empty scope → `dm`. Empty thread → `-`.
- Slack: channel=slack, scope=team_id or `dm`, chat=channel id, thread=`thread_ts` or `-`.
- Discord: scope=guild id or `dm`, chat=channel id, thread=`-` unless the channel is already a thread (then thread=channel id, chat=parent if easy — otherwise chat=channel, thread=-`).
- Telegram: scope=`dm` for private else chat id, chat=chat id, thread=message_thread_id or `-`.

Old `slack_C…` keys are not rewritten. New messages use v2 only.

## Commands

Parse **after** stripping leading bot mentions (`<@U…>`, `<@!id>`, `@name`).

| Input | kind | rest |
|---|---|---|
| `/code fix it` / `!code fix it` | `code` | `fix it` |
| `/stop` / `!stop` | `stop` | |
| `/status` / `!status` | `status` | |
| `!approve` / `/approve` | `approve` | optional id |
| `!deny` / `/deny` | `deny` | optional id |
| anything else | `chat` | original stripped text |

`/code` with empty rest is invalid → reply `"Usage: /code <task>"`. Do **not** start a workflow or sandbox.

## Inflight

`SessionInflightLock.acquire(session_id) -> bool`. Second acquire fails. `release` in finally.

Default: drop + reply `"Already working on this thread."` (English, one line). No queue.

## Gateway routing

`ChannelGateway.dispatch` (after existing circuit breaker wrap of the inner run):

1. acquire inflight for `message.session_id` — if false, return busy text
2. parse command
3. `chat` → existing `_run_workflow`
4. `code` / `stop` / `status` / `approve` / `deny` → coding port
5. release inflight

`/code` must **not** call `execute_workflow`.

Coding port (injectable; default uses `neos.coding.runtime` services):

- create_task only if `channels.coding_invoke` is true **and** `channels.coding_owner_user_id` is non-empty. Else refuse with a short message. Bind `session_id → task_id`.
- `/stop` / `/status` / approve/deny use the bound task. None bound → `"No coding task in this thread."`

Do not implement Slack Block Kit cards or media downloads.

## Adapter duties

After Phase 0 gate:

- `receive_message` sets `session_id` via `build_session_key`.
- `metadata["thread_id"]` = Slack `thread_ts` or `ts`; Discord reply target message id; Telegram `message_id`.
- `send_response(channel_id, content, *, thread_id=None)` posts **in that thread/reply**. Slack: `thread_ts`. Discord: `message.reply` if possible else channel send. Telegram: `reply_to_message_id`.
- Optional ACK: Slack/Discord eyes on start, white_check_mark/x on finish. Do not fail dispatch if reactions fail.
- Existing Phase 0 silent-drop tests must stay green.

## Config

`ChannelConfig.coding_invoke: bool = False`
`ChannelConfig.coding_owner_user_id: str = ""`

Env: `CHANNEL_CODING_INVOKE`, `CHANNEL_CODING_OWNER_USER_ID`.

## Out of scope

Pairing, Block Kit, media in, Discord auto-thread, session key rewrite of old transcripts, ChannelGateway replacement.
