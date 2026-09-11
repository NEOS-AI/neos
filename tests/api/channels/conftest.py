"""Shared fixtures for channel adapter gate tests."""

from __future__ import annotations

import pytest

from neos.config.schema import (
    AppConfig,
    ChannelConfig,
    ChannelPrincipal,
    DiscordChannelConfig,
    SlackChannelConfig,
    TelegramChannelConfig,
)
from neos.config.settings import Settings


@pytest.fixture
def restore_channel_settings():
    import neos.config.settings as settings_module

    original = settings_module.settings
    yield
    settings_module.settings = original


def install_channel_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    allowed_users: list[str],
    require_mention: bool = True,
    allowed_channels: list[str] | None = None,
    ignored_channels: list[str] | None = None,
    slack: SlackChannelConfig | None = None,
    discord: DiscordChannelConfig | None = None,
    telegram: TelegramChannelConfig | None = None,
    coding_invoke: bool = False,
    coding_owner_user_id: str = "",
    principals: list[ChannelPrincipal] | None = None,
) -> Settings:
    import neos.config.settings as settings_module

    config = AppConfig(
        channels=ChannelConfig(
            require_mention=require_mention,
            allowed_users=allowed_users,
            allowed_channels=allowed_channels or [],
            ignored_channels=ignored_channels or [],
            slack=slack or SlackChannelConfig(),
            discord=discord or DiscordChannelConfig(),
            telegram=telegram or TelegramChannelConfig(),
            coding_invoke=coding_invoke,
            coding_owner_user_id=coding_owner_user_id,
            principals=principals or [],
        )
    )
    installed = Settings(config=config)
    monkeypatch.setattr(settings_module, "settings", installed)
    return installed
