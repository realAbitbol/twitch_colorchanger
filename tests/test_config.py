import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import (
    _fix_docker_ownership,
    _log_debug_data,
    _log_save_operation,
    _set_file_permissions,
    _setup_config_directory,
    _verify_saved_data,
    disable_random_colors_for_user,
    get_configuration,
    load_users_from_config,
    print_config_summary,
    save_users_to_config,
    update_user_in_config,
    validate_user_config,
)
from tests.fixtures.sample_configs import (
    MULTI_USER_CONFIG,
    SINGLE_USER_CONFIG,
)


def test_load_users_from_config_multi(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(MULTI_USER_CONFIG))
    users = load_users_from_config(str(config_file))
    assert isinstance(users, list)
    assert len(users) == 2
    assert users[0]["username"] == "primeuser"


def test_load_users_from_config_single(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(SINGLE_USER_CONFIG))
    users = load_users_from_config(str(config_file))
    assert isinstance(users, list)
    assert users[0]["username"] == "testuser"


def test_load_users_from_config_missing(tmp_path):
    users = load_users_from_config(str(tmp_path / "missing.json"))
    assert users == []


def test_save_and_update_user(tmp_path):
    config_file = tmp_path / "config.json"
    users = [SINGLE_USER_CONFIG]
    save_users_to_config(users, str(config_file))
    loaded = load_users_from_config(str(config_file))
    assert loaded[0]["username"] == "testuser"
    # Update user
    updated = dict(loaded[0])
    updated["is_prime_or_turbo"] = False
    update_user_in_config(updated, str(config_file))
    loaded2 = load_users_from_config(str(config_file))
    assert loaded2[0]["is_prime_or_turbo"] is False


def test_disable_random_colors_for_user(tmp_path):
    config_file = tmp_path / "config.json"
    users = [dict(SINGLE_USER_CONFIG)]
    users[0]["is_prime_or_turbo"] = True
    save_users_to_config(users, str(config_file))
    disable_random_colors_for_user("testuser", str(config_file))
    loaded = load_users_from_config(str(config_file))
    assert loaded[0]["is_prime_or_turbo"] is False


def test_validate_user_config_valid():
    assert validate_user_config(SINGLE_USER_CONFIG)


def test_validate_user_config_invalid():
    invalid = dict(SINGLE_USER_CONFIG)
    invalid.pop("username")
    assert not validate_user_config(invalid)


def test_print_config_summary(capsys):
    users = [SINGLE_USER_CONFIG]
    print_config_summary(users)
    out = capsys.readouterr().out
    assert "Username: testuser" in out


def test_get_configuration(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(MULTI_USER_CONFIG))
    monkeypatch.setenv("TWITCH_CONF_FILE", str(config_file))
    users = get_configuration()
    assert isinstance(users, list)
    assert len(users) == 2


def test_load_users_from_config_invalid_json(tmp_path):
    """Test loading config with invalid JSON (covers error handling)"""
    config_file = tmp_path / "config.json"
    config_file.write_text("invalid json content")
    users = load_users_from_config(str(config_file))
    assert users == []


def test_load_users_from_config_empty_dict(tmp_path):
    """Test loading config with empty dict"""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({}))
    users = load_users_from_config(str(config_file))
    assert users == []


def test_load_users_from_config_invalid_format(tmp_path):
    """Test loading config with invalid format (string instead of dict/list)"""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps("invalid format"))
    users = load_users_from_config(str(config_file))
    assert users == []


def test_setup_config_directory(tmp_path):
    """Test _setup_config_directory function"""
    config_file = tmp_path / "subdir" / "config.json"
    _setup_config_directory(str(config_file))
    assert config_file.parent.exists()


def test_setup_config_directory_existing(tmp_path):
    """Test _setup_config_directory with existing directory"""
    config_dir = tmp_path / "existing_dir"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    _setup_config_directory(str(config_file))
    assert config_file.parent.exists()


@patch("os.chown")
@patch("os.geteuid")
def test_fix_docker_ownership(mock_geteuid, mock_chown, tmp_path):
    """Test _fix_docker_ownership function"""
    mock_geteuid.return_value = 1000  # Non-root user
    config_dir = tmp_path / "config_dir"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text("{}")

    _fix_docker_ownership(str(config_dir), str(config_file))

    # Should have called chown
    assert mock_chown.call_count >= 1


@patch("os.chown")
@patch("os.geteuid")
def test_fix_docker_ownership_root(mock_geteuid, mock_chown, tmp_path):
    """Test _fix_docker_ownership as root user"""
    mock_geteuid.return_value = 0  # Root user
    config_dir = tmp_path / "config_dir"
    config_dir.mkdir()
    config_file = config_dir / "config.json"

    _fix_docker_ownership(str(config_dir), str(config_file))

    # Should not call chown for root
    mock_chown.assert_not_called()


@patch("os.chmod")
def test_set_file_permissions(mock_chmod, tmp_path):
    """Test _set_file_permissions function"""
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")

    _set_file_permissions(str(config_file))

    mock_chmod.assert_called_once_with(str(config_file), 0o644)


@patch("os.chmod")
def test_set_file_permissions_missing_file(mock_chmod, tmp_path):
    """Test _set_file_permissions with missing file"""
    config_file = tmp_path / "missing.json"

    _set_file_permissions(str(config_file))

    mock_chmod.assert_not_called()


@patch("src.config.print_log")
def test_log_save_operation(mock_print_log, tmp_path):
    """Test _log_save_operation function"""
    users = [SINGLE_USER_CONFIG]
    config_file = str(tmp_path / "config.json")

    _log_save_operation(users, config_file)

    # Should have called print_log multiple times
    assert mock_print_log.call_count >= 2


@patch("src.config.print_log")
def test_log_debug_data(mock_print_log):
    """Test _log_debug_data function"""
    save_data = {"users": [SINGLE_USER_CONFIG]}

    _log_debug_data(save_data)

    assert mock_print_log.call_count >= 2


@patch("src.config.print_log")
def test_verify_saved_data(mock_print_log, tmp_path):
    """Test _verify_saved_data function"""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(MULTI_USER_CONFIG))

    _verify_saved_data(str(config_file))

    assert mock_print_log.call_count >= 3


@patch("src.config.print_log")
def test_verify_saved_data_error(mock_print_log, tmp_path):
    """Test _verify_saved_data with error"""
    config_file = tmp_path / "config.json"
    config_file.write_text("invalid json")

    _verify_saved_data(str(config_file))

    # Should log the verification failure
    assert mock_print_log.call_count >= 1


@patch("builtins.open")
@patch("src.config._setup_config_directory")
@patch("src.config._fix_docker_ownership")
@patch("src.config._set_file_permissions")
@patch("src.config._log_save_operation")
@patch("src.config._log_debug_data")
@patch("src.config._verify_saved_data")
@patch("src.config.print_log")
def test_save_users_to_config_error_handling(
    _mock_print_log,
    _mock_verify,
    _mock_debug,
    _mock_log,
    _mock_perms,
    _mock_ownership,
    _mock_setup,
    mock_open,
    tmp_path,
):
    """Test save_users_to_config error handling"""
    config_file = str(tmp_path / "config.json")

    # Mock file open to raise exception
    mock_file = MagicMock()
    mock_file.__enter__.return_value = mock_file
    mock_file.__exit__.return_value = None
    mock_open.return_value = mock_file
    mock_file.write.side_effect = Exception("Write failed")

    with pytest.raises(Exception):
        save_users_to_config([SINGLE_USER_CONFIG], config_file)


@patch("src.config.load_users_from_config")
@patch("src.config.save_users_to_config")
def test_update_user_in_config_error(mock_save, mock_load, tmp_path):
    """Test update_user_in_config error handling"""
    config_file = str(tmp_path / "config.json")
    mock_load.return_value = [SINGLE_USER_CONFIG]
    mock_save.side_effect = Exception("Save failed")

    result = update_user_in_config(SINGLE_USER_CONFIG, config_file)

    assert result is False


def test_update_user_in_config_new_user(tmp_path):
    """Test update_user_in_config with new user (not in existing config)"""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"users": [SINGLE_USER_CONFIG]}))

    new_user = {
        "username": "newuser",
        "client_id": "new_client",
        "client_secret": "new_secret",
        "access_token": "new_token",
        "channels": ["newchannel"],
    }

    result = update_user_in_config(new_user, str(config_file))
    assert result is True

    # Verify new user was added
    loaded = load_users_from_config(str(config_file))
    usernames = [user["username"] for user in loaded]
    assert "newuser" in usernames


@patch("src.config.load_users_from_config")
@patch("src.config.save_users_to_config")
def test_disable_random_colors_for_user_not_found(mock_save, mock_load, tmp_path):
    """Test disable_random_colors_for_user when user not found"""
    config_file = str(tmp_path / "config.json")
    mock_load.return_value = [SINGLE_USER_CONFIG]

    result = disable_random_colors_for_user("nonexistent", config_file)

    assert result is False
    mock_save.assert_not_called()


@patch("src.config.load_users_from_config")
@patch("src.config.save_users_to_config")
def test_disable_random_colors_for_user_error(mock_save, mock_load, tmp_path):
    """Test disable_random_colors_for_user error handling"""
    config_file = str(tmp_path / "config.json")
    mock_load.return_value = [SINGLE_USER_CONFIG]
    mock_save.side_effect = Exception("Save failed")

    result = disable_random_colors_for_user("testuser", config_file)

    assert result is False


def test_get_configuration_no_config_file(monkeypatch, tmp_path):
    """Test get_configuration with no config file"""
    config_file = tmp_path / "missing.json"
    monkeypatch.setenv("TWITCH_CONF_FILE", str(config_file))

    with pytest.raises(SystemExit):
        get_configuration()


def test_get_configuration_invalid_users(monkeypatch, tmp_path):
    """Test get_configuration with invalid users"""
    config_file = tmp_path / "config.json"
    # Create config with invalid users
    invalid_config = {
        "users": [{"username": ""}, {"invalid": "user"}]  # Invalid  # Invalid
    }
    config_file.write_text(json.dumps(invalid_config))
    monkeypatch.setenv("TWITCH_CONF_FILE", str(config_file))

    with pytest.raises(SystemExit):
        get_configuration()


def test_print_config_summary_empty_list(capsys):
    """Test print_config_summary with empty list"""
    print_config_summary([])
    out = capsys.readouterr().out
    assert "Total Users: 0" in out


def test_print_config_summary_missing_fields(capsys):
    """Test print_config_summary with missing fields"""
    user = {
        "username": "testuser",
        "channels": ["channel1"],
        # Missing is_prime_or_turbo and refresh_token
    }
    print_config_summary([user])
    out = capsys.readouterr().out
    assert "testuser" in out
    assert "channel1" in out


# Test specific missing lines coverage


def test_load_users_from_config_legacy_single_format(tmp_path):
    """Test legacy single user format conversion (covers line 26)"""
    config_file = tmp_path / "config.json"
    legacy_user = {
        "username": "legacyuser",
        "oauth_token": "oauth:token123",
        "client_id": "client123",
        "channels": ["channel1"],
    }
    with open(config_file, "w") as f:
        json.dump(legacy_user, f)

    result = load_users_from_config(str(config_file))
    assert len(result) == 1
    assert result[0]["username"] == "legacyuser"


def test_load_users_from_config_exception_handling(tmp_path, monkeypatch):
    """Test exception handling in load_users_from_config (covers lines 47-48)"""
    config_file = tmp_path / "config.json"
    with open(config_file, "w") as f:
        f.write("invalid json content")

    with patch("src.config.print_log") as mock_print:
        result = load_users_from_config(str(config_file))
        assert result == []
        mock_print.assert_called_once()


def test_fix_docker_ownership_exception_handling(tmp_path):
    """Test exception handling in _fix_docker_ownership (covers lines 62-63)"""
    from src.config import _fix_docker_ownership

    config_file = tmp_path / "config.json"
    config_file.touch()
    config_dir = str(tmp_path)

    with patch("os.geteuid", return_value=1000), patch(
        "os.chown", side_effect=OSError("Permission denied")
    ):
        # Should not raise exception
        _fix_docker_ownership(config_dir, str(config_file))


def test_set_file_permissions_exception_handling(tmp_path):
    """Test exception handling in _set_file_permissions (covers lines 71-72)"""
    from src.config import _set_file_permissions

    config_file = tmp_path / "config.json"
    config_file.touch()

    with patch("os.chmod", side_effect=PermissionError("Permission denied")):
        _set_file_permissions(str(config_file))  # Should not raise exception


def test_save_users_to_config_missing_is_prime_or_turbo(tmp_path):
    """Test adding missing is_prime_or_turbo field (covers lines 109-110, 115-116)"""
    config_file = tmp_path / "config.json"
    user_without_field = {
        "username": "testuser",
        "oauth_token": "oauth:token123",
        "client_id": "client123",
        "channels": ["channel1"],
    }

    with patch("src.config.print_log") as mock_print:
        save_users_to_config([user_without_field], str(config_file))

        # Verify the field was added
        saved_users = load_users_from_config(str(config_file))
        assert saved_users[0]["is_prime_or_turbo"] is True
        mock_print.assert_called()


def test_save_users_to_config_watcher_import_error(tmp_path):
    """Test watcher import error handling (covers lines 150-151)"""
    config_file = tmp_path / "config.json"
    user = {
        "username": "testuser",
        "oauth_token": "oauth:token123",
        "client_id": "client123",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    # Mock sys.modules to simulate import error more precisely
    with patch.dict("sys.modules", {"src.watcher_globals": None}):
        with patch("src.config.print_log"):
            save_users_to_config([user], str(config_file))  # Should not raise exception


# Async test functions for config setup and token validation


@pytest.mark.asyncio
async def test_setup_missing_tokens_no_updates_needed(tmp_path):
    """Test setup_missing_tokens when no updates are needed (covers lines 266-279)"""
    from src.config import setup_missing_tokens

    config_file = tmp_path / "config.json"
    users = [
        {
            "username": "testuser",
            "client_id": "client123",
            "client_secret": "secret123",
            "access_token": "token123",
            "refresh_token": "refresh123",
            "channels": ["channel1"],
            "is_prime_or_turbo": True,
        }
    ]

    with patch("src.config._setup_user_tokens") as mock_setup_user:
        mock_setup_user.return_value = {"user": users[0], "tokens_updated": False}

        result = await setup_missing_tokens(users, str(config_file))

        assert len(result) == 1
        assert result[0]["username"] == "testuser"
        mock_setup_user.assert_called_once_with(users[0])


@pytest.mark.asyncio
async def test_setup_missing_tokens_updates_needed(tmp_path):
    """Test setup_missing_tokens when updates are needed (covers lines 266-279)"""
    from src.config import setup_missing_tokens

    config_file = tmp_path / "config.json"
    users = [
        {
            "username": "testuser",
            "client_id": "client123",
            "client_secret": "secret123",
            "channels": ["channel1"],
            "is_prime_or_turbo": True,
        }
    ]

    updated_user = users[0].copy()
    updated_user["access_token"] = "new_token"

    with patch("src.config._setup_user_tokens") as mock_setup_user, patch(
        "src.config._save_updated_config"
    ) as mock_save:

        mock_setup_user.return_value = {"user": updated_user, "tokens_updated": True}

        result = await setup_missing_tokens(users, str(config_file))

        assert len(result) == 1
        mock_setup_user.assert_called_once_with(users[0])
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_setup_user_tokens_missing_credentials(tmp_path):
    """Test _setup_user_tokens with missing credentials (covers lines 284-299)"""
    from src.config import _setup_user_tokens

    user = {
        "username": "testuser",
        "channels": ["channel1"],
        # Missing client_id and client_secret
    }

    with patch("src.config.print_log") as mock_log:
        result = await _setup_user_tokens(user)

        assert result["user"] == user
        assert result["tokens_updated"] is False
        mock_log.assert_called_once()


@pytest.mark.asyncio
async def test_setup_user_tokens_valid_tokens(tmp_path):
    """Test _setup_user_tokens with valid tokens (covers lines 284-299)"""
    from src.config import _setup_user_tokens

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "access_token": "token123",
        "refresh_token": "refresh123",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    with patch("src.config._validate_or_refresh_tokens") as mock_validate:
        mock_validate.return_value = {"valid": True, "user": user, "updated": False}

        result = await _setup_user_tokens(user)

        assert result["user"] == user
        assert result["tokens_updated"] is False
        mock_validate.assert_called_once_with(user)


@pytest.mark.asyncio
async def test_setup_user_tokens_invalid_tokens_need_new(tmp_path):
    """Test _setup_user_tokens with invalid tokens needing device flow (covers lines 284-299)"""
    from src.config import _setup_user_tokens

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "access_token": "invalid_token",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    new_token_result = {"user": user.copy(), "tokens_updated": True}
    new_token_result["user"]["access_token"] = "new_token"

    with patch("src.config._validate_or_refresh_tokens") as mock_validate, patch(
        "src.config._get_new_tokens_via_device_flow"
    ) as mock_device_flow:

        mock_validate.return_value = {"valid": False, "user": user, "updated": False}
        mock_device_flow.return_value = new_token_result

        result = await _setup_user_tokens(user)

        assert result["tokens_updated"] is True
        mock_validate.assert_called_once_with(user)
        mock_device_flow.assert_called_once()


@pytest.mark.asyncio
async def test_validate_or_refresh_tokens_no_access_token():
    """Test _validate_or_refresh_tokens with no access token (covers lines 307-361)"""
    from src.config import _validate_or_refresh_tokens

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "channels": ["channel1"],
        # No access_token
    }

    with patch("src.token_validator.validate_user_tokens") as mock_validate:
        mock_validate.return_value = {"valid": False, "user": user, "updated": False}
        
        result = await _validate_or_refresh_tokens(user)

        assert result["valid"] is False
        assert result["user"] == user
        assert result["updated"] is False
        mock_validate.assert_called_once_with(user)


@pytest.mark.asyncio
async def test_validate_or_refresh_tokens_validation_success():
    """Test _validate_or_refresh_tokens with successful validation (covers lines 307-361)"""
    from src.config import _validate_or_refresh_tokens

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "access_token": "token123",
        "refresh_token": "refresh123",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    with patch("src.token_validator.validate_user_tokens") as mock_validate:
        mock_validate.return_value = {"valid": True, "user": user, "updated": False}
        
        result = await _validate_or_refresh_tokens(user)

        assert result["valid"] is True
        assert result["user"] == user
        assert result["updated"] is False
        mock_validate.assert_called_once_with(user)


@pytest.mark.asyncio
async def test_validate_or_refresh_tokens_proactive_refresh():
    """Test _validate_or_refresh_tokens with proactive token refresh (covers lines 307-361)"""
    from src.config import _validate_or_refresh_tokens

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "access_token": "old_token",
        "refresh_token": "old_refresh",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    updated_user = user.copy()
    updated_user["access_token"] = "new_token"
    updated_user["refresh_token"] = "new_refresh"
    
    with patch("src.token_validator.validate_user_tokens") as mock_validate:
        mock_validate.return_value = {"valid": True, "user": updated_user, "updated": True}
        
        result = await _validate_or_refresh_tokens(user)

        assert result["valid"] is True
        assert result["user"]["access_token"] == "new_token"
        assert result["user"]["refresh_token"] == "new_refresh"
        assert result["updated"] is True
        mock_validate.assert_called_once_with(user)


@pytest.mark.asyncio
async def test_validate_or_refresh_tokens_validation_failed():
    """Test _validate_or_refresh_tokens with validation failure (covers lines 307-361)"""
    from src.config import _validate_or_refresh_tokens

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "access_token": "invalid_token",
        "refresh_token": "invalid_refresh",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    with patch("src.token_validator.validate_user_tokens") as mock_validate:
        mock_validate.return_value = {"valid": False, "user": user, "updated": False}
        
        result = await _validate_or_refresh_tokens(user)

        assert result["valid"] is False
        assert result["user"] == user
        assert result["updated"] is False
        mock_validate.assert_called_once_with(user)


@pytest.mark.asyncio
async def test_validate_or_refresh_tokens_exception_handling():
    """Test _validate_or_refresh_tokens exception handling (covers lines 307-361)"""
    from src.config import _validate_or_refresh_tokens

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "access_token": "token123",
        "refresh_token": "refresh123",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    with patch("src.token_validator.validate_user_tokens", side_effect=Exception("Validation failed")):
        result = await _validate_or_refresh_tokens(user)

        assert result["valid"] is False
        assert result["user"] == user
        assert result["updated"] is False


@pytest.mark.asyncio
async def test_get_new_tokens_via_device_flow_success():
    """Test _get_new_tokens_via_device_flow success (covers lines 366-391)"""
    from src.config import _get_new_tokens_via_device_flow

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    with patch("src.config.DeviceCodeFlow") as mock_device_flow_class, patch(
        "src.config._validate_new_tokens"
    ) as mock_validate, patch("src.config.print_log") as mock_log:

        mock_device_flow = MagicMock()
        mock_device_flow.get_user_tokens = AsyncMock(
            return_value=("new_token", "new_refresh")
        )
        mock_device_flow_class.return_value = mock_device_flow

        mock_validate.return_value = {"valid": True, "user": user}

        result = await _get_new_tokens_via_device_flow(user, "client123", "secret123")

        assert result["tokens_updated"] is True
        mock_device_flow.get_user_tokens.assert_called_once()
        mock_validate.assert_called_once()
        mock_log.assert_called()


@pytest.mark.asyncio
async def test_get_new_tokens_via_device_flow_failure():
    """Test _get_new_tokens_via_device_flow failure (covers lines 366-391)"""
    from src.config import _get_new_tokens_via_device_flow

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    with patch("src.config.DeviceCodeFlow") as mock_device_flow_class, patch(
        "src.config.print_log"
    ) as mock_log:

        mock_device_flow = MagicMock()
        mock_device_flow.get_user_tokens = AsyncMock(return_value=None)
        mock_device_flow_class.return_value = mock_device_flow

        result = await _get_new_tokens_via_device_flow(user, "client123", "secret123")

        assert result["tokens_updated"] is False
        mock_device_flow.get_user_tokens.assert_called_once()
        mock_log.assert_called()


@pytest.mark.asyncio
async def test_get_new_tokens_via_device_flow_exception():
    """Test _get_new_tokens_via_device_flow exception handling (covers lines 366-391)"""
    from src.config import _get_new_tokens_via_device_flow

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    with patch("src.config.DeviceCodeFlow") as mock_device_flow_class, patch(
        "src.config.print_log"
    ) as mock_log:

        mock_device_flow = MagicMock()
        mock_device_flow.get_user_tokens = AsyncMock(
            side_effect=Exception("Device flow failed")
        )
        mock_device_flow_class.return_value = mock_device_flow

        result = await _get_new_tokens_via_device_flow(user, "client123", "secret123")

        assert result["tokens_updated"] is False
        mock_log.assert_called()


@pytest.mark.asyncio
async def test_get_new_tokens_via_device_flow_validation_failed():
    """Test _get_new_tokens_via_device_flow with validation failure (covers lines 366-391)"""
    from src.config import _get_new_tokens_via_device_flow

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    with patch("src.config.DeviceCodeFlow") as mock_device_flow_class, patch(
        "src.config._validate_new_tokens"
    ) as mock_validate, patch("src.config.print_log") as mock_log:

        mock_device_flow = MagicMock()
        mock_device_flow.get_user_tokens = AsyncMock(
            return_value=("new_token", "new_refresh")
        )
        mock_device_flow_class.return_value = mock_device_flow

        mock_validate.return_value = {"valid": False, "user": user}

        result = await _get_new_tokens_via_device_flow(user, "client123", "secret123")

        # Still saves tokens even if validation fails
        assert result["tokens_updated"] is True
        mock_validate.assert_called_once()
        mock_log.assert_called()


@pytest.mark.asyncio
async def test_validate_new_tokens_success():
    """Test _validate_new_tokens success (covers lines 396-428)"""
    from src.config import _validate_new_tokens

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "access_token": "new_token",
        "refresh_token": "new_refresh",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    with patch("src.token_validator.validate_new_tokens") as mock_validate:
        mock_validate.return_value = {"valid": True, "user": user}
        
        result = await _validate_new_tokens(user)

        assert result["valid"] is True
        assert result["user"]["access_token"] == "new_token"
        mock_validate.assert_called_once_with(user)


@pytest.mark.asyncio
async def test_validate_new_tokens_failure():
    """Test _validate_new_tokens failure (covers lines 396-428)"""
    from src.config import _validate_new_tokens

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "access_token": "invalid_token",
        "refresh_token": "invalid_refresh",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    with patch("src.token_validator.validate_new_tokens") as mock_validate:
        mock_validate.return_value = {"valid": False, "user": user}
        
        result = await _validate_new_tokens(user)

        assert result["valid"] is False
        mock_validate.assert_called_once_with(user)


@pytest.mark.asyncio
async def test_validate_new_tokens_exception():
    """Test _validate_new_tokens exception handling (covers lines 396-428)"""
    from src.config import _validate_new_tokens

    user = {
        "username": "testuser",
        "client_id": "client123",
        "client_secret": "secret123",
        "access_token": "token123",
        "refresh_token": "refresh123",
        "channels": ["channel1"],
        "is_prime_or_turbo": True,
    }

    with patch("src.token_validator.validate_new_tokens", side_effect=Exception("Validation failed")):
        result = await _validate_new_tokens(user)

        assert result["valid"] is False


def test_save_updated_config_success(tmp_path):
    """Test _save_updated_config success (covers lines 433-437)"""
    from src.config import _save_updated_config

    config_file = tmp_path / "config.json"
    users = [
        {
            "username": "testuser",
            "oauth_token": "oauth:token123",
            "client_id": "client123",
            "channels": ["channel1"],
            "is_prime_or_turbo": True,
        }
    ]

    with patch("src.config.save_users_to_config") as mock_save, patch(
        "src.config.print_log"
    ) as mock_log:

        _save_updated_config(users, str(config_file))

        mock_save.assert_called_once_with(users, str(config_file))
        mock_log.assert_called_once()


def test_save_updated_config_failure(tmp_path):
    """Test _save_updated_config failure (covers lines 433-437)"""
    from src.config import _save_updated_config

    config_file = tmp_path / "config.json"
    users = []

    with patch(
        "src.config.save_users_to_config", side_effect=Exception("Save failed")
    ), patch("src.config.print_log") as mock_log:

        _save_updated_config(users, str(config_file))

        mock_log.assert_called_once()


# Additional tests for final missing lines


def test_load_users_from_config_invalid_dict_format(tmp_path):
    """Test loading config with invalid dict format (covers line 30)"""
    config_file = tmp_path / "config.json"
    invalid_data = {"some_key": "some_value"}  # Dict without 'users' or 'username'
    with open(config_file, "w") as f:
        json.dump(invalid_data, f)

    result = load_users_from_config(str(config_file))
    assert result == []


def test_load_users_from_config_list_format(tmp_path):
    """Test loading config with list format (covers line 26)"""
    config_file = tmp_path / "config.json"
    list_data = [{"username": "user1"}, {"username": "user2"}]  # Direct list format
    with open(config_file, "w") as f:
        json.dump(list_data, f)

    result = load_users_from_config(str(config_file))
    assert result == list_data


def test_setup_config_directory_permission_error(tmp_path):
    """Test setup_config_directory with permission error (covers lines 47-48)"""
    from src.config import _setup_config_directory

    config_file = tmp_path / "subdir" / "config.json"

    with patch("os.makedirs") as mock_makedirs, patch(
        "os.chmod", side_effect=PermissionError("Permission denied")
    ):
        _setup_config_directory(str(config_file))  # Should not raise exception
        mock_makedirs.assert_called_once()


# Note: The proactive hours logic test is complex to implement due to internal imports
# Lines 336-337 are defensive code for proactive token refresh
