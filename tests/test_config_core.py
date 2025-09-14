from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.core import (
    _confirm_missing_scopes,
    _missing_scopes,
    _validate_or_invalidate_scopes_dataclass,
    load_users_from_config,
    normalize_user_channels,
    save_users_to_config,
    setup_missing_tokens,
    update_user_in_config,
)
from src.config.model import UserConfig

# Users scenario tests (8 tests)

def test_load_users_from_config_success(tmp_path: Path):
    """Test loading users from a valid config file."""
    config_file = tmp_path / "config.json"
    users_data = [
        {"username": "alice", "channels": ["alice"], "access_token": "a" * 30},
        {"username": "bob", "channels": ["bob"], "access_token": "b" * 30},
    ]
    config_file.write_text(json.dumps({"users": users_data}))
    loaded = load_users_from_config(str(config_file))
    assert len(loaded) == 2
    assert loaded[0]["username"] == "alice"
    assert loaded[1]["username"] == "bob"


def test_load_users_from_config_file_not_found(tmp_path: Path):
    """Test loading users when config file does not exist."""
    config_file = tmp_path / "missing.json"
    loaded = load_users_from_config(str(config_file))
    assert loaded == []


def test_save_users_to_config_normalizes_and_saves(tmp_path: Path):
    """Test saving users normalizes them and saves to file."""
    config_file = tmp_path / "config.json"
    users = [
        {"username": "  Alice  ", "channels": ["#Alice", "alice"], "access_token": "a" * 30},
    ]
    save_users_to_config(users, str(config_file))
    data = json.loads(config_file.read_text())
    assert data["users"][0]["username"] == "Alice"
    assert data["users"][0]["channels"] == ["alice"]


def test_save_users_to_config_verifies_readback(tmp_path: Path):
    """Test saving users verifies readback after save."""
    config_file = tmp_path / "config.json"
    users = [
        {"username": "alice", "channels": ["alice"], "access_token": "a" * 30},
    ]
    save_users_to_config(users, str(config_file))
    # If verification fails, it would raise an exception, so no assert needed if it passes


def test_update_user_in_config_valid_user(tmp_path: Path):
    """Test updating a valid user in config."""
    config_file = tmp_path / "config.json"
    initial_users = [{"username": "alice", "channels": ["alice"], "access_token": "a" * 30}]
    config_file.write_text(json.dumps({"users": initial_users}))
    new_user = {"username": "bob", "channels": ["bob"], "access_token": "b" * 30}
    success = update_user_in_config(new_user, str(config_file))
    assert success is True
    data = json.loads(config_file.read_text())
    assert len(data["users"]) == 2


def test_update_user_in_config_invalid_user(tmp_path: Path):
    """Test updating an invalid user in config fails."""
    config_file = tmp_path / "config.json"
    initial_users = [{"username": "alice", "channels": ["alice"], "access_token": "a" * 30}]
    config_file.write_text(json.dumps({"users": initial_users}))
    invalid_user = {"username": "ab", "channels": ["ab"], "access_token": "short"}  # invalid
    success = update_user_in_config(invalid_user, str(config_file))
    assert success is False


def test_update_user_in_config_merge_existing(tmp_path: Path):
    """Test updating merges with existing user."""
    config_file = tmp_path / "config.json"
    initial_users = [{"username": "alice", "channels": ["alice"], "access_token": "a" * 30}]
    config_file.write_text(json.dumps({"users": initial_users}))
    updated_user = {"username": "alice", "channels": ["alice", "newchan"], "access_token": "a" * 30}
    success = update_user_in_config(updated_user, str(config_file))
    assert success is True
    data = json.loads(config_file.read_text())
    user = data["users"][0]
    assert "newchan" in user["channels"]


def test_normalize_user_channels_no_changes(tmp_path: Path):
    """Test normalizing user channels when no changes needed."""
    config_file = tmp_path / "config.json"
    users = [UserConfig(username="alice", channels=["alice"], access_token="a" * 30)]
    normalized, changed = normalize_user_channels(users, str(config_file))
    assert changed is False
    assert len(normalized) == 1


# Tokens scenario tests (7 tests)

@pytest.mark.asyncio
async def test_setup_missing_tokens_no_provisioning_needed():
    """Test setup missing tokens when all tokens are valid."""
    users = [
        UserConfig(username="alice", channels=["alice"], access_token="a" * 30, refresh_token="refresh",
                   client_id="cid", client_secret="sec")
    ]
    with patch('src.auth_token.provisioner.TokenProvisioner') as mock_provisioner_class, \
         patch('src.api.twitch.TwitchAPI') as mock_api_class:
        mock_provisioner = MagicMock()
        mock_provisioner_class.return_value = mock_provisioner
        mock_api = MagicMock()
        mock_api_class.return_value = mock_api
        mock_api.validate_token = AsyncMock(return_value={"scopes": ["chat:read", "user:read:chat", "user:manage:chat_color"]})
        updated = await setup_missing_tokens(users, "dummy.conf")
        assert len(updated) == 1
        assert updated[0].access_token == "a" * 30


@pytest.mark.asyncio
async def test_setup_missing_tokens_provisioning_success():
    """Test setup missing tokens provisions new tokens successfully."""
    users = [
        UserConfig(username="alice", channels=["alice"], access_token=None, refresh_token=None,
                   client_id="c" * 10, client_secret="s" * 10)
    ]
    with patch('src.auth_token.provisioner.TokenProvisioner') as mock_provisioner_class, \
         patch('src.api.twitch.TwitchAPI') as mock_api_class, \
         patch('src.config.core._save_updated_config_dataclass') as mock_save:
        mock_provisioner = MagicMock()
        mock_provisioner_class.return_value = mock_provisioner
        mock_provisioner.provision = AsyncMock(return_value=("new_access", "new_refresh", None))
        mock_api = MagicMock()
        mock_api_class.return_value = mock_api
        updated = await setup_missing_tokens(users, "dummy.conf")
        assert len(updated) == 1
        assert updated[0].access_token == "new_access"
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_setup_missing_tokens_provisioning_failure():
    """Test setup missing tokens when provisioning fails."""
    users = [
        UserConfig(username="alice", channels=["alice"], access_token=None, refresh_token=None,
                   client_id="c" * 10, client_secret="s" * 10)
    ]
    with patch('src.auth_token.provisioner.TokenProvisioner') as mock_provisioner_class, \
         patch('src.api.twitch.TwitchAPI') as mock_api_class, \
         patch('src.config.core._save_updated_config_dataclass') as mock_save:
        mock_provisioner = MagicMock()
        mock_provisioner_class.return_value = mock_provisioner
        mock_provisioner.provision = AsyncMock(return_value=(None, None, None))
        mock_api = MagicMock()
        mock_api_class.return_value = mock_api
        updated = await setup_missing_tokens(users, "dummy.conf")
        assert len(updated) == 1
        assert updated[0].access_token is None
        mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_validate_or_invalidate_scopes_dataclass_valid_tokens():
    """Test validating scopes when tokens are valid."""
    user = UserConfig(username="alice", access_token="a" * 30, refresh_token="refresh")
    mock_api = MagicMock()
    mock_api.validate_token = AsyncMock(return_value={"scopes": ["chat:read", "user:read:chat", "user:manage:chat_color"]})
    required = {"chat:read", "user:read:chat", "user:manage:chat_color"}
    retained = await _validate_or_invalidate_scopes_dataclass(user, "a" * 30, "refresh", mock_api, required)
    assert retained is True
    assert user.access_token == "a" * 30


@pytest.mark.asyncio
async def test_validate_or_invalidate_scopes_dataclass_missing_scopes():
    """Test validating scopes invalidates when scopes are missing."""
    user = UserConfig(username="alice", access_token="a" * 30, refresh_token="refresh")
    mock_api = MagicMock()
    mock_api.validate_token = AsyncMock(return_value={"scopes": ["chat:read"]})
    required = {"chat:read", "user:read:chat", "user:manage:chat_color"}
    retained = await _validate_or_invalidate_scopes_dataclass(user, "invalid", "refresh", mock_api, required)
    assert retained is False
    assert user.access_token is None


def test_missing_scopes_identifies_missing():
    """Test identifying missing scopes."""
    required = {"chat:read", "user:read:chat", "user:manage:chat_color"}
    current = {"chat:read"}
    missing = _missing_scopes(required, current)
    assert set(missing) == {"user:read:chat", "user:manage:chat_color"}


@pytest.mark.asyncio
async def test_confirm_missing_scopes_revalidates():
    """Test confirming missing scopes via revalidation."""
    mock_api = MagicMock()
    mock_api.validate_token = AsyncMock(return_value={"scopes": ["chat:read", "user:read:chat"]})
    required = {"chat:read", "user:read:chat", "user:manage:chat_color"}
    missing, _ = await _confirm_missing_scopes(mock_api, "token", required)
    assert "user:manage:chat_color" in missing
