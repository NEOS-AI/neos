# Phase 0 adapter contract

Do not invent a second gate. Use `neos/api/channels/authz.py` only.

## Required behavior

In `_handle_message`, BEFORE typing indicators and BEFORE `self._gateway.dispatch`:

```python
from neos.api.channels.authz import (
    GateContext,
    evaluate_channel_gate,
    policy_from_settings,
    slack_text_mentions_bot,      # slack only
    telegram_text_mentions_bot,   # telegram only
)

ctx = GateContext(
    channel_type=self.channel_type,
    platform_user_id=...,
    channel_id=...,
    text=...,
    is_dm=...,
    is_bot=...,
    is_self=...,
    mentioned=...,
)
decision = evaluate_channel_gate(ctx, policy_from_settings(self.channel_type))
if not decision.allowed:
    logger.info("[XAdapter] drop reason=%s channel=%s user=%s", ...)
    return
```

Dropped messages: **silence**. Do not send an error. Do not call dispatch.

## Platform mapping

### Slack (`adapters/slack.py`)
- `is_bot`: `bool(message.get("bot_id"))` or `message.get("subtype") == "bot_message"`
- `is_self`: `self._bot_user_id` set and `str(message.get("user")) == self._bot_user_id`
- `is_dm`: `message.get("channel_type") == "im"`
- `mentioned`: `slack_text_mentions_bot(text, self._bot_user_id or "")`
- Cache `_bot_user_id` on start via `auth_test` best-effort; tests may assign it.
- Existing `bot_id` early return can stay (then gate still runs for humans).

### Discord (`adapters/discord.py`)
- `is_self`: `self._client and message.author == self._client.user`
- `is_bot`: `getattr(message.author, "bot", False)`
- `is_dm`: `message.guild is None`
- `mentioned`: bot user in `message.mentions`, or content contains `<@id>` / `<@!id>`
- Do NOT enable `voice_states`. Do NOT change session_id format.

### Telegram (`adapters/telegram.py`)
- `is_bot`: `bool(getattr(effective_user, "is_bot", False))`
- `is_self`: bot id available and `effective_user.id == bot.id`
- `is_dm`: `effective_chat.type == "private"`
- `mentioned`: `telegram_text_mentions_bot(text, bot.username)` or mention entities targeting the bot
- Still ignore `filters.COMMAND` as today.

## Tests you must add (pytest.mark.no_db)

File: `tests/api/channels/test_<platform>_adapter.py`

Use `tests/api/channels/conftest.py` → `install_channel_settings`.

Fake gateway:

```python
class FakeGateway:
    def __init__(self):
        self.calls = []
    async def dispatch(self, message):
        self.calls.append(message)
        return "ok"
```

Do not start the real bot / socket / polling.

Cases:
1. Mentioned allowlisted user → dispatch called once
2. Channel message, no mention, require_mention=True → dispatch not called, no reply
3. User not in allowlist → dispatch not called (silence)
4. Empty allowlist (fail-closed) → dispatch not called
5. DM without mention, user allowlisted → dispatch called
6. Bot/self message → dispatch not called
7. Ignored channel → dispatch not called even if mentioned

## Out of scope
Session key v2, thread_ts replies, /code, reactions, pairing, Block Kit, ChannelGateway rewrite, Hermes copy-paste.
