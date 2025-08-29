import os
import tempfile
import json
import pytest
from unittest.mock import patch, MagicMock
from src.config import (
    load_users_from_config, save_users_to_config, update_user_in_config,
    disable_random_colors_for_user, validate_user_config, get_configuration,
    print_config_summary, _setup_config_directory, _fix_docker_ownership,
    _set_file_permissions, _log_save_operation, _log_debug_data, _verify_saved_data
)
from tests.fixtures.sample_configs import SINGLE_USER_CONFIG, MULTI_USER_CONFIG, MINIMAL_CONFIG

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


@patch('os.chown')
@patch('os.geteuid')
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


@patch('os.chown')
@patch('os.geteuid')
def test_fix_docker_ownership_root(mock_geteuid, mock_chown, tmp_path):
    """Test _fix_docker_ownership as root user"""
    mock_geteuid.return_value = 0  # Root user
    config_dir = tmp_path / "config_dir"
    config_dir.mkdir()
    config_file = config_dir / "config.json"

    _fix_docker_ownership(str(config_dir), str(config_file))

    # Should not call chown for root
    mock_chown.assert_not_called()


@patch('os.chmod')
def test_set_file_permissions(mock_chmod, tmp_path):
    """Test _set_file_permissions function"""
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")

    _set_file_permissions(str(config_file))

    mock_chmod.assert_called_once_with(str(config_file), 0o644)


@patch('os.chmod')
def test_set_file_permissions_missing_file(mock_chmod, tmp_path):
    """Test _set_file_permissions with missing file"""
    config_file = tmp_path / "missing.json"

    _set_file_permissions(str(config_file))

    mock_chmod.assert_not_called()


@patch('src.config.print_log')
def test_log_save_operation(mock_print_log, tmp_path):
    """Test _log_save_operation function"""
    users = [SINGLE_USER_CONFIG]
    config_file = str(tmp_path / "config.json")

    _log_save_operation(users, config_file)

    # Should have called print_log multiple times
    assert mock_print_log.call_count >= 2


@patch('src.config.print_log')
def test_log_debug_data(mock_print_log):
    """Test _log_debug_data function"""
    save_data = {'users': [SINGLE_USER_CONFIG]}

    _log_debug_data(save_data)

    assert mock_print_log.call_count >= 2


@patch('src.config.print_log')
def test_verify_saved_data(mock_print_log, tmp_path):
    """Test _verify_saved_data function"""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(MULTI_USER_CONFIG))

    _verify_saved_data(str(config_file))

    assert mock_print_log.call_count >= 3


@patch('src.config.print_log')
def test_verify_saved_data_error(mock_print_log, tmp_path):
    """Test _verify_saved_data with error"""
    config_file = tmp_path / "config.json"
    config_file.write_text("invalid json")

    _verify_saved_data(str(config_file))

    # Should log the verification failure
    assert mock_print_log.call_count >= 1


@patch('builtins.open')
@patch('src.config._setup_config_directory')
@patch('src.config._fix_docker_ownership')
@patch('src.config._set_file_permissions')
@patch('src.config._log_save_operation')
@patch('src.config._log_debug_data')
@patch('src.config._verify_saved_data')
@patch('src.config.print_log')
def test_save_users_to_config_error_handling(mock_print_log, mock_verify, mock_debug, mock_log,
                                             mock_perms, mock_ownership, mock_setup,
                                             mock_open, tmp_path):
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


@patch('src.config.load_users_from_config')
@patch('src.config.save_users_to_config')
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
        "channels": ["newchannel"]
    }

    result = update_user_in_config(new_user, str(config_file))
    assert result is True

    # Verify new user was added
    loaded = load_users_from_config(str(config_file))
    usernames = [user['username'] for user in loaded]
    assert 'newuser' in usernames


@patch('src.config.load_users_from_config')
@patch('src.config.save_users_to_config')
def test_disable_random_colors_for_user_not_found(mock_save, mock_load, tmp_path):
    """Test disable_random_colors_for_user when user not found"""
    config_file = str(tmp_path / "config.json")
    mock_load.return_value = [SINGLE_USER_CONFIG]

    result = disable_random_colors_for_user("nonexistent", config_file)

    assert result is False
    mock_save.assert_not_called()


@patch('src.config.load_users_from_config')
@patch('src.config.save_users_to_config')
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
        "users": [
            {"username": ""},  # Invalid
            {"invalid": "user"}  # Invalid
        ]
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
