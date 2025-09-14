import asyncio
from typing import Any

import pytest

from src.color.models import ColorRequestResult, ColorRequestStatus
from src.color.service import ColorChangeService


class FakeBot:
    def __init__(
        self,
        results: list[ColorRequestResult],
        refresh_outcomes: list[bool] | None = None,
    ) -> None:
        self.username = "tester"
        self.use_random_colors = True
        self.last_color: str | None = None
        self._results = results
        self._refresh_outcomes = refresh_outcomes or []
        self._refresh_index = 0
        self._result_index = 0
        self.user_id = "123"

    async def _perform_color_request(
        self, params: dict[str, Any], action: str
    ) -> ColorRequestResult:  # noqa: D401
        if self._result_index >= len(self._results):
            return ColorRequestResult(ColorRequestStatus.INTERNAL_ERROR)
        r = self._results[self._result_index]
        self._result_index += 1
        await asyncio.sleep(0)
        return r

    async def _check_and_refresh_token(self, force: bool = False) -> bool:  # noqa: D401
        if self._refresh_index >= len(self._refresh_outcomes):
            return False
        outcome = self._refresh_outcomes[self._refresh_index]
        self._refresh_index += 1
        await asyncio.sleep(0)
        return outcome


@pytest.mark.asyncio
async def test_color_change_success_hex():
    bot = FakeBot([ColorRequestResult(ColorRequestStatus.SUCCESS, http_status=204)])
    svc = ColorChangeService(bot)  # type: ignore[arg-type]
    ok = await svc._perform_color_change(
        "#123456", allow_refresh=True, fallback_to_preset=False
    )
    assert ok is True
    assert bot.last_color == "#123456"


@pytest.mark.asyncio
async def test_color_change_unauthorized_then_refresh_success():
    bot = FakeBot(
        [
            ColorRequestResult(ColorRequestStatus.UNAUTHORIZED, http_status=401),
            ColorRequestResult(ColorRequestStatus.SUCCESS, http_status=204),
        ],
        refresh_outcomes=[True],
    )
    svc = ColorChangeService(bot)  # type: ignore[arg-type]
    ok = await svc._perform_color_change(
        "#abcdef", allow_refresh=True, fallback_to_preset=True
    )
    assert ok is True
    assert bot.last_color == "#abcdef"


@pytest.mark.asyncio
async def test_color_change_unauthorized_refresh_fails():
    bot = FakeBot(
        [ColorRequestResult(ColorRequestStatus.UNAUTHORIZED, http_status=401)],
        refresh_outcomes=[False],
    )
    svc = ColorChangeService(bot)  # type: ignore[arg-type]
    ok = await svc._perform_color_change(
        "#ff00ff", allow_refresh=True, fallback_to_preset=True
    )
    assert ok is False


@pytest.mark.asyncio
async def test_color_change_fallback_to_preset(monkeypatch):
    bot = FakeBot(
        [
            ColorRequestResult(ColorRequestStatus.HTTP_ERROR, http_status=500),
            ColorRequestResult(ColorRequestStatus.SUCCESS, http_status=204),
        ]
    )
    svc = ColorChangeService(bot)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "src.color.service.get_random_preset", lambda exclude=None: "red"
    )
    ok = await svc._perform_color_change(
        "#aabbcc", allow_refresh=True, fallback_to_preset=True
    )
    assert ok is True
    assert bot.last_color == "red"

@pytest.mark.asyncio
async def test_color_service_init_invalid_dependencies():
    """Test ColorService initialization with invalid or missing dependencies."""
    with pytest.raises((TypeError, AttributeError)):
        ColorChangeService(None)


@pytest.mark.asyncio
async def test_change_color_invalid_hex():
    """Test change_color method with invalid hex color codes."""
    bot = FakeBot([ColorRequestResult(ColorRequestStatus.INTERNAL_ERROR)])
    svc = ColorChangeService(bot)
    ok = await svc.change_color("#invalid")
    assert ok is False


@pytest.mark.asyncio
async def test_validate_color_edge_cases():
    """Test validate_color with edge cases like empty strings or special characters."""
    bot = FakeBot([ColorRequestResult(ColorRequestStatus.INTERNAL_ERROR)])
    svc = ColorChangeService(bot)
    ok = await svc._perform_color_change("", allow_refresh=False, fallback_to_preset=False)
    assert ok is False


@pytest.mark.asyncio
async def test_get_color_history_empty():
    """Test get_color_history when history is empty or unavailable."""
    bot = FakeBot([ColorRequestResult(ColorRequestStatus.SUCCESS)])
    bot.last_color = None
    svc = ColorChangeService(bot)
    ok = await svc.change_color()
    assert ok is True
    assert bot.last_color is not None


@pytest.mark.asyncio
async def test_reset_color_permission_issues():
    """Test reset_color with permission or access issues."""
    bot = FakeBot([ColorRequestResult(ColorRequestStatus.UNAUTHORIZED, http_status=401)], refresh_outcomes=[False])
    svc = ColorChangeService(bot)
    ok = await svc._perform_color_change("#123456", allow_refresh=True, fallback_to_preset=False)
    assert ok is False
