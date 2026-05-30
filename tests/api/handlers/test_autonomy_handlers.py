import os
from types import SimpleNamespace

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.handlers.autonomy_handlers import get_autonomy_preference


@pytest.mark.asyncio
async def test_get_autonomy_preference_falls_back_for_invalid_stored_value():
    response = await get_autonomy_preference(
        current_user=SimpleNamespace(
            user_id="user_123",
            preferences={"autonomy_level": "bad"},
        )
    )

    assert response.autonomy_level == 1
