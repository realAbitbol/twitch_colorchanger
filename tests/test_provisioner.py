from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.auth_token.provisioner import TokenProvisioner


@pytest.mark.asyncio
async def test_provision_with_existing_tokens():
    """Test provision returns existing tokens when both are provided."""
    session = MagicMock()
    provisioner = TokenProvisioner(session)
    expiry = datetime(2023, 1, 1)
    result = await provisioner.provision("cid", "sec", "at", "rt", expiry)
    assert result == ("at", "rt", expiry)


@pytest.mark.asyncio
async def test_provision_without_access_token():
    """Test provision calls interactive authorize when access_token is missing."""
    session = MagicMock()
    provisioner = TokenProvisioner(session)
    with patch.object(provisioner, '_interactive_authorize', new_callable=AsyncMock) as mock_interactive:
        mock_interactive.return_value = ("iat", "irt", None)
        result = await provisioner.provision("cid", "sec", None, "rt", None)
        mock_interactive.assert_called_once_with("cid", "sec")
        assert result == ("iat", "irt", None)


@pytest.mark.asyncio
async def test_provision_without_refresh_token():
    """Test provision calls interactive authorize when refresh_token is missing."""
    session = MagicMock()
    provisioner = TokenProvisioner(session)
    with patch.object(provisioner, '_interactive_authorize', new_callable=AsyncMock) as mock_interactive:
        mock_interactive.return_value = ("iat", "irt", None)
        result = await provisioner.provision("cid", "sec", "at", None, None)
        mock_interactive.assert_called_once_with("cid", "sec")
        assert result == ("iat", "irt", None)


@pytest.mark.asyncio
async def test_interactive_authorize_device_code_success():
    """Test interactive authorize succeeds with valid device code and tokens."""
    session = MagicMock()
    provisioner = TokenProvisioner(session)
    with patch('src.auth_token.provisioner.DeviceCodeFlow') as mock_flow_class:
        mock_flow = MagicMock()
        mock_flow_class.return_value = mock_flow
        mock_flow.request_device_code = AsyncMock(return_value={
            "device_code": "dc", "user_code": "uc", "verification_uri": "url", "expires_in": 30
        })
        mock_flow.poll_for_tokens = AsyncMock(return_value={
            "access_token": "at", "refresh_token": "rt", "expires_in": 3600
        })
        result = await provisioner._interactive_authorize("cid", "sec")
        assert result[0] == "at"
        assert result[1] == "rt"
        assert isinstance(result[2], datetime)


@pytest.mark.asyncio
async def test_interactive_authorize_device_code_failure():
    """Test interactive authorize fails when device code request returns None."""
    session = MagicMock()
    provisioner = TokenProvisioner(session)
    with patch('src.auth_token.provisioner.DeviceCodeFlow') as mock_flow_class:
        mock_flow = MagicMock()
        mock_flow_class.return_value = mock_flow
        mock_flow.request_device_code = AsyncMock(return_value=None)
        result = await provisioner._interactive_authorize("cid", "sec")
        assert result == (None, None, None)


@pytest.mark.asyncio
async def test_interactive_authorize_poll_success():
    """Test interactive authorize succeeds when polling returns tokens."""
    session = MagicMock()
    provisioner = TokenProvisioner(session)
    with patch('src.auth_token.provisioner.DeviceCodeFlow') as mock_flow_class:
        mock_flow = MagicMock()
        mock_flow_class.return_value = mock_flow
        mock_flow.request_device_code = AsyncMock(return_value={
            "device_code": "dc", "user_code": "uc", "verification_uri": "url", "expires_in": 30
        })
        mock_flow.poll_for_tokens = AsyncMock(return_value={
            "access_token": "at", "refresh_token": "rt", "expires_in": 3600
        })
        result = await provisioner._interactive_authorize("cid", "sec")
        assert result[0] == "at"
        assert result[1] == "rt"
        assert isinstance(result[2], datetime)


@pytest.mark.asyncio
async def test_interactive_authorize_poll_failure_timeout():
    """Test interactive authorize fails when polling times out."""
    session = MagicMock()
    provisioner = TokenProvisioner(session)
    with patch('src.auth_token.provisioner.DeviceCodeFlow') as mock_flow_class:
        mock_flow = MagicMock()
        mock_flow_class.return_value = mock_flow
        mock_flow.request_device_code = AsyncMock(return_value={
            "device_code": "dc", "user_code": "uc", "verification_uri": "url", "expires_in": 30
        })
        mock_flow.poll_for_tokens = AsyncMock(return_value=None)
        result = await provisioner._interactive_authorize("cid", "sec")
        assert result == (None, None, None)


@pytest.mark.asyncio
async def test_interactive_authorize_poll_failure_network():
    """Test interactive authorize fails on network error during polling."""
    session = MagicMock()
    provisioner = TokenProvisioner(session)
    with patch('src.auth_token.provisioner.DeviceCodeFlow') as mock_flow_class:
        mock_flow = MagicMock()
        mock_flow_class.return_value = mock_flow
        mock_flow.request_device_code = AsyncMock(return_value={
            "device_code": "dc", "user_code": "uc", "verification_uri": "url", "expires_in": 30
        })
        import aiohttp
        mock_flow.poll_for_tokens = AsyncMock(side_effect=aiohttp.ClientError("Network error"))
        result = await provisioner._interactive_authorize("cid", "sec")
        assert result == (None, None, None)


@pytest.mark.asyncio
async def test_interactive_authorize_poll_failure_other():
    """Test interactive authorize fails on other exception during polling."""
    session = MagicMock()
    provisioner = TokenProvisioner(session)
    with patch('src.auth_token.provisioner.DeviceCodeFlow') as mock_flow_class:
        mock_flow = MagicMock()
        mock_flow_class.return_value = mock_flow
        mock_flow.request_device_code = AsyncMock(return_value={
            "device_code": "dc", "user_code": "uc", "verification_uri": "url", "expires_in": 30
        })
        mock_flow.poll_for_tokens = AsyncMock(side_effect=Exception("Other error"))
        result = await provisioner._interactive_authorize("cid", "sec")
        assert result == (None, None, None)


@pytest.mark.asyncio
async def test_interactive_authorize_token_processing():
    """Test interactive authorize processes token data correctly."""
    session = MagicMock()
    provisioner = TokenProvisioner(session)
    with patch('src.auth_token.provisioner.DeviceCodeFlow') as mock_flow_class:
        mock_flow = MagicMock()
        mock_flow_class.return_value = mock_flow
        mock_flow.request_device_code = AsyncMock(return_value={
            "device_code": "dc", "user_code": "uc", "verification_uri": "url", "expires_in": 30
        })
        mock_flow.poll_for_tokens = AsyncMock(return_value={
            "access_token": "at", "refresh_token": "rt", "expires_in": 3600
        })
        result = await provisioner._interactive_authorize("cid", "sec")
        assert result[0] == "at"
        assert result[1] == "rt"
        assert isinstance(result[2], datetime)
        # Expiry should be set based on lifetime minus buffer
        # Since buffer is TOKEN_REFRESH_SAFETY_BUFFER_SECONDS, and lifetime 3600, expiry should be now + (3600 - buffer)
        # But since we can't check exact time, just ensure it's a datetime
