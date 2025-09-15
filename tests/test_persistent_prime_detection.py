import asyncio
from typing import Any

import pytest

from src.color.models import ColorRequestResult, ColorRequestStatus
from src.color.service import ColorChangeService


class FakeBot:
    def __init__(self, results: list[ColorRequestResult]) -> None:
        self.username = "tester"
        self.use_random_colors = True
        self.last_color: str | None = None
        self._results = results
        self._result_index = 0
        self.user_id = "123"
        self.persist_called = False


    async def _perform_color_request(self, params: dict[str, Any], action: str) -> ColorRequestResult:  # noqa: D401
        if self._result_index >= len(self._results):
            return ColorRequestResult(ColorRequestStatus.INTERNAL_ERROR)
        r = self._results[self._result_index]
        self._result_index += 1
        await asyncio.sleep(0)
        return r

    async def _check_and_refresh_token(self, force: bool = False) -> bool:  # noqa: D401
        await asyncio.sleep(0)
        return False

    async def on_persistent_prime_detection(self) -> None:
        self.persist_called = True
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_disables_random_hex_after_repeated_hex_rejections():
    # Two separate invocations each starting with a hex 400 should trigger disable on 2nd strike.
    # Provide a success in between for the preset fallback of the first invocation.
    bot = FakeBot(
        [
            # First call: hex 400 -> strike 1
            ColorRequestResult(ColorRequestStatus.HTTP_ERROR, http_status=400),
            # Fallback preset success completes first call successfully
            ColorRequestResult(ColorRequestStatus.SUCCESS, http_status=204),
            # Second call: another hex 400 -> strike 2 triggers disable
            ColorRequestResult(ColorRequestStatus.HTTP_ERROR, http_status=400),
        ]
    )
    svc = ColorChangeService(bot)  # type: ignore[arg-type]

    await svc._perform_color_change("#112233", allow_refresh=True, fallback_to_preset=True)
    assert bot.use_random_colors is True

    await svc._perform_color_change("#445566", allow_refresh=True, fallback_to_preset=True)
    assert bot.use_random_colors is False
    assert bot.persist_called is True


@pytest.mark.asyncio
async def test_hex_success_resets_strikes(monkeypatch):
    # First call: hex 400 with preset fallback success (does not reset),
    # Second call: non-preset success should reset strikes to 0.
    bot = FakeBot(
        [
            ColorRequestResult(ColorRequestStatus.HTTP_ERROR, http_status=400),
            # preset fallback success for first call
            ColorRequestResult(ColorRequestStatus.SUCCESS, http_status=204),
            # second call: non-preset success
            ColorRequestResult(ColorRequestStatus.SUCCESS, http_status=204),
        ]
    )
    svc = ColorChangeService(bot)  # type: ignore[arg-type]

    await svc._perform_color_change("#abcdef", allow_refresh=True, fallback_to_preset=True)

    # Perform a successful hex change, which should reset strikes
    ok2 = await svc._perform_color_change("#fedcba", allow_refresh=True, fallback_to_preset=True)
    assert ok2 is True
    # Internal attribute maintained on the bot by service
    assert getattr(bot, "_hex_rejection_strikes", 0) == 0
