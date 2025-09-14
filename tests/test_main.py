from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from src.main import main


@pytest.mark.asyncio
async def test_main_config_load_success():
    """Test main successfully loads configuration."""
    mock_config = [MagicMock()]
    with patch('src.main.get_configuration', return_value=mock_config) as mock_get_config, \
         patch('src.main.normalize_user_channels', return_value=(mock_config, False)) as mock_normalize, \
         patch('src.main.setup_missing_tokens', new_callable=AsyncMock, return_value=mock_config) as mock_setup_tokens, \
         patch('src.main.print_config_summary') as mock_print_summary, \
         patch('src.main.run_bots', new_callable=AsyncMock) as mock_run_bots, \
         patch('src.main.emit_startup_instructions'), \
         patch('builtins.print'):
        await main()
        mock_get_config.assert_called_once()
        mock_normalize.assert_called_once_with(mock_config, "twitch_colorchanger.conf")
        mock_setup_tokens.assert_called_once_with(mock_config, "twitch_colorchanger.conf")
        mock_print_summary.assert_called_once_with(mock_config)
        mock_run_bots.assert_called_once()


@pytest.mark.asyncio
async def test_main_config_load_failure():
    """Test main handles config load failure."""
    with patch('src.main.get_configuration', side_effect=Exception("Config error")), \
         patch('src.main.log_error') as mock_log_error, \
         patch('sys.exit') as mock_exit, \
         patch('src.main.emit_startup_instructions'), \
         patch('builtins.print'):
        await main()
        mock_log_error.assert_called_once_with("Main application error", ANY)
        mock_exit.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_main_config_normalization():
    """Test main normalizes user channels."""
    mock_config = [MagicMock()]
    normalized_config = [MagicMock()]
    with patch('src.main.get_configuration', return_value=mock_config), \
         patch('src.main.normalize_user_channels', return_value=(normalized_config, True)) as mock_normalize, \
         patch('src.main.setup_missing_tokens', new_callable=AsyncMock, return_value=normalized_config) as mock_setup_tokens, \
         patch('src.main.print_config_summary') as mock_print_summary, \
         patch('src.main.run_bots', new_callable=AsyncMock), \
         patch('src.main.emit_startup_instructions'), \
         patch('builtins.print'):
        await main()
        mock_normalize.assert_called_once_with(mock_config, "twitch_colorchanger.conf")
        mock_setup_tokens.assert_called_once_with(normalized_config, "twitch_colorchanger.conf")
        mock_print_summary.assert_called_once_with(normalized_config)


@pytest.mark.asyncio
async def test_main_token_setup_success():
    """Test main successfully sets up tokens."""
    mock_config = [MagicMock()]
    with patch('src.main.get_configuration', return_value=mock_config), \
         patch('src.main.normalize_user_channels', return_value=(mock_config, False)), \
         patch('src.main.setup_missing_tokens', new_callable=AsyncMock, return_value=mock_config) as mock_setup_tokens, \
         patch('src.main.print_config_summary'), \
         patch('src.main.run_bots', new_callable=AsyncMock) as mock_run_bots, \
         patch('src.main.emit_startup_instructions'), \
         patch('builtins.print'):
        await main()
        mock_setup_tokens.assert_called_once_with(mock_config, "twitch_colorchanger.conf")
        mock_run_bots.assert_called_once()


@pytest.mark.asyncio
async def test_main_token_setup_failure():
    """Test main handles token setup failure."""
    mock_config = [MagicMock()]
    with patch('src.main.get_configuration', return_value=mock_config), \
         patch('src.main.normalize_user_channels', return_value=(mock_config, False)), \
         patch('src.main.setup_missing_tokens', new_callable=AsyncMock, side_effect=Exception("Token error")), \
         patch('src.main.log_error') as mock_log_error, \
         patch('sys.exit') as mock_exit, \
         patch('src.main.emit_startup_instructions'), \
         patch('builtins.print'):
        await main()
        mock_log_error.assert_called_once_with("Main application error", ANY)
        mock_exit.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_main_run_bots_success():
    """Test main successfully runs bots."""
    mock_config = [MagicMock()]
    with patch('src.main.get_configuration', return_value=mock_config), \
         patch('src.main.normalize_user_channels', return_value=(mock_config, False)), \
         patch('src.main.setup_missing_tokens', new_callable=AsyncMock, return_value=mock_config), \
         patch('src.main.print_config_summary'), \
         patch('src.main.run_bots', new_callable=AsyncMock) as mock_run_bots, \
         patch('src.main.emit_startup_instructions'), \
         patch('builtins.print'):
        await main()
        mock_run_bots.assert_called_once()


@pytest.mark.asyncio
async def test_main_run_bots_failure():
    """Test main handles run bots failure."""
    mock_config = [MagicMock()]
    with patch('src.main.get_configuration', return_value=mock_config), \
         patch('src.main.normalize_user_channels', return_value=(mock_config, False)), \
         patch('src.main.setup_missing_tokens', new_callable=AsyncMock, return_value=mock_config), \
         patch('src.main.print_config_summary'), \
         patch('src.main.run_bots', new_callable=AsyncMock, side_effect=Exception("Run bots error")), \
         patch('src.main.log_error') as mock_log_error, \
         patch('sys.exit') as mock_exit, \
         patch('src.main.emit_startup_instructions'), \
         patch('builtins.print'):
        await main()
        mock_log_error.assert_called_once_with("Main application error", ANY)
        mock_exit.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_main_exceptions_handling():
    """Test main handles general exceptions."""
    with patch('src.main.emit_startup_instructions', side_effect=Exception("Startup error")), \
         patch('src.main.log_error') as mock_log_error, \
         patch('sys.exit') as mock_exit, \
         patch('builtins.print'):
        await main()
        mock_log_error.assert_called_once_with("Main application error", ANY)
        mock_exit.assert_called_once_with(1)
