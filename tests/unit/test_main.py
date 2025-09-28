"""
Unit tests for main.py
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import sys

from src.main import main, run


class TestMain:
    """Test class for main function."""

    @pytest.mark.asyncio
    async def test_main_success(self):
        """Test main function success path."""
        async def mock_setup(loaded_config, config_file):
            return []

        async def mock_run_bots(users_config_dicts, config_file):
            pass

        with patch('src.main.get_configuration') as mock_get_config, \
              patch('src.main.normalize_user_channels') as mock_normalize, \
              patch('src.main.setup_missing_tokens', side_effect=mock_setup) as mock_setup_patch, \
              patch('src.main.print_config_summary') as mock_print, \
              patch('src.main.run_bots', side_effect=mock_run_bots) as mock_run_bots_patch, \
              patch('src.main.emit_startup_instructions') as mock_emit:

            mock_get_config.return_value = {}
            mock_normalize.return_value = ({}, None)

            await main()

            mock_get_config.assert_called_once()
            mock_normalize.assert_called_once()
            mock_setup_patch.assert_called_once()
            mock_print.assert_called_once()
            mock_run_bots_patch.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_exception(self):
        """Test main function exception handling."""
        with patch('src.main.get_configuration', side_effect=Exception("Test error")), \
             patch('src.main.log_error') as mock_log_error, \
             patch('builtins.print') as mock_print:

            with pytest.raises(SystemExit):
                await main()

            mock_log_error.assert_called_once()
            args = mock_log_error.call_args[0]
            assert args[0] == "Main application error"
            assert isinstance(args[1], Exception)
            assert str(args[1]) == "Test error"

    @pytest.mark.asyncio
    async def test_main_keyboard_interrupt(self):
        """Test main function keyboard interrupt handling."""
        with patch('src.main.get_configuration', side_effect=KeyboardInterrupt), \
             patch('builtins.print') as mock_print:

            # Should not raise
            await main()

    def test_run_success(self):
        """Test run function success path."""
        with patch('asyncio.run') as mock_asyncio_run:
            run()
            mock_asyncio_run.assert_called_once()

    def test_run_keyboard_interrupt(self):
        """Test run function keyboard interrupt handling."""
        with patch('asyncio.run', side_effect=KeyboardInterrupt), \
             patch('sys.exit') as mock_exit:
            run()
            mock_exit.assert_called_once_with(0)

    def test_run_exception(self):
        """Test run function exception handling."""
        mock_run = Mock(side_effect=Exception("Test error"))
        with patch('asyncio.run', mock_run), \
              patch('src.main.log_error') as mock_log_error, \
              patch('sys.exit') as mock_exit:
            run()
            mock_log_error.assert_called_once()
            args = mock_log_error.call_args[0]
            assert args[0] == "Top-level error"
            assert isinstance(args[1], Exception)
            assert str(args[1]) == "Test error"
            mock_exit.assert_called_once_with(1)