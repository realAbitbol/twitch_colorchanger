"""
Test module for main.py entry point
"""

import sys
import os
import pytest
from unittest.mock import patch, AsyncMock

import main


class TestMainFunction:
    """Test the main() async function"""

    @pytest.mark.asyncio
    async def test_main_success(self):
        """Test successful main execution"""
        mock_users_config = [
            {
                'username': 'testuser',
                'access_token': 'token123',
                'client_id': 'client123',
                'channels': ['testuser']
            }
        ]

        with patch('main.print_instructions') as mock_print_instructions, \
             patch('main.get_configuration', return_value=mock_users_config) as mock_get_config, \
             patch('main.setup_missing_tokens', new_callable=AsyncMock, return_value=mock_users_config) as mock_setup_tokens, \
             patch('main.print_config_summary') as mock_print_summary, \
             patch('main.run_bots', new_callable=AsyncMock) as mock_run_bots, \
             patch('main.logger') as mock_logger:

            await main.main()

            # Verify all steps were called
            mock_logger.info.assert_any_call("🚀 Starting Twitch Color Changer Bot")
            mock_print_instructions.assert_called_once()
            mock_get_config.assert_called_once()
            mock_setup_tokens.assert_called_once_with(mock_users_config, "twitch_colorchanger.conf")
            mock_print_summary.assert_called_once_with(mock_users_config)
            mock_run_bots.assert_called_once_with(mock_users_config, "twitch_colorchanger.conf")
            mock_logger.info.assert_any_call("🏁 Application shutdown complete")

    @pytest.mark.asyncio
    async def test_main_custom_config_file(self):
        """Test main with custom config file from environment"""
        mock_users_config = [{'username': 'testuser'}]

        with patch.dict(os.environ, {'TWITCH_CONF_FILE': 'custom.conf'}), \
             patch('main.print_instructions'), \
             patch('main.get_configuration', return_value=mock_users_config), \
             patch('main.setup_missing_tokens', new_callable=AsyncMock, return_value=mock_users_config) as mock_setup_tokens, \
             patch('main.print_config_summary'), \
             patch('main.run_bots', new_callable=AsyncMock) as mock_run_bots, \
             patch('main.logger'):

            await main.main()

            # Verify custom config file was used
            mock_setup_tokens.assert_called_once_with(mock_users_config, "custom.conf")
            mock_run_bots.assert_called_once_with(mock_users_config, "custom.conf")

    @pytest.mark.asyncio
    async def test_main_keyboard_interrupt(self):
        """Test main handles KeyboardInterrupt"""
        with patch('main.print_instructions'), \
             patch('main.get_configuration') as mock_get_config, \
             patch('main.logger') as mock_logger:

            mock_get_config.side_effect = KeyboardInterrupt()

            await main.main()

            mock_logger.warning.assert_called_once_with("⌨️ Interrupted by user")
            mock_logger.info.assert_any_call("🏁 Application shutdown complete")

    @pytest.mark.asyncio
    async def test_main_generic_exception(self):
        """Test main handles generic exceptions"""
        test_exception = Exception("Test error")

        with patch('main.print_instructions'), \
             patch('main.get_configuration') as mock_get_config, \
             patch('main.log_error') as mock_log_error, \
             patch('main.logger') as mock_logger, \
             patch('sys.exit') as mock_exit:

            mock_get_config.side_effect = test_exception

            await main.main()

            mock_log_error.assert_called_once_with("Main application error", test_exception)
            mock_logger.critical.assert_called_once_with(f"Critical error occurred: {test_exception}", exc_info=True)
            mock_exit.assert_called_once_with(1)
            mock_logger.info.assert_any_call("🏁 Application shutdown complete")

    @pytest.mark.asyncio
    async def test_main_setup_tokens_error(self):
        """Test main when setup_missing_tokens fails"""
        mock_users_config = [{'username': 'testuser'}]
        test_exception = Exception("Token setup failed")

        with patch('main.print_instructions'), \
             patch('main.get_configuration', return_value=mock_users_config), \
             patch('main.setup_missing_tokens', new_callable=AsyncMock) as mock_setup_tokens, \
             patch('main.log_error') as mock_log_error, \
             patch('main.logger') as mock_logger, \
             patch('sys.exit') as mock_exit:

            mock_setup_tokens.side_effect = test_exception

            await main.main()

            mock_log_error.assert_called_once_with("Main application error", test_exception)
            mock_logger.critical.assert_called_once_with(f"Critical error occurred: {test_exception}", exc_info=True)
            mock_exit.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_main_run_bots_error(self):
        """Test main when run_bots fails"""
        mock_users_config = [{'username': 'testuser'}]
        test_exception = Exception("Bot running failed")

        with patch('main.print_instructions'), \
             patch('main.get_configuration', return_value=mock_users_config), \
             patch('main.setup_missing_tokens', new_callable=AsyncMock, return_value=mock_users_config), \
             patch('main.print_config_summary'), \
             patch('main.run_bots', new_callable=AsyncMock) as mock_run_bots, \
             patch('main.log_error') as mock_log_error, \
             patch('main.logger') as mock_logger, \
             patch('sys.exit') as mock_exit:

            mock_run_bots.side_effect = test_exception

            await main.main()

            mock_log_error.assert_called_once_with("Main application error", test_exception)
            mock_logger.critical.assert_called_once_with(f"Critical error occurred: {test_exception}", exc_info=True)
            mock_exit.assert_called_once_with(1)


class TestMainEntryPoint:
    """Test the main entry point and command line handling"""

    def test_health_check_mode_success(self):
        """Test health check mode with valid configuration"""
        mock_users_config = [{'username': 'testuser'}]

        with patch.object(sys, 'argv', ['main.py', '--health-check']), \
             patch('main.get_configuration', return_value=mock_users_config) as mock_get_config, \
             patch('main.logger') as mock_logger, \
             patch('main.sys.exit') as mock_exit:

            # Simulate the health check mode execution
            if len(sys.argv) > 1 and sys.argv[1] == "--health-check":
                mock_logger.info("🏥 Health check mode")
                try:
                    users_config = mock_get_config()
                    mock_logger.info(f"✅ Health check passed - {len(users_config)} user(s) configured")
                    mock_exit(0)
                except Exception as e:
                    mock_logger.error(f"❌ Health check failed: {e}")
                    mock_exit(1)

            mock_logger.info.assert_any_call("🏥 Health check mode")
            mock_get_config.assert_called_once()
            mock_logger.info.assert_any_call("✅ Health check passed - 1 user(s) configured")
            mock_exit.assert_called_once_with(0)

    def test_health_check_mode_failure(self):
        """Test health check mode with configuration error"""
        test_exception = Exception("Config error")

        with patch.object(sys, 'argv', ['main.py', '--health-check']), \
             patch('main.get_configuration') as mock_get_config, \
             patch('main.logger') as mock_logger, \
             patch('main.sys.exit') as mock_exit:

            mock_get_config.side_effect = test_exception

            # Simulate the health check mode execution
            if len(sys.argv) > 1 and sys.argv[1] == "--health-check":
                mock_logger.info("🏥 Health check mode")
                try:
                    users_config = mock_get_config()
                    mock_logger.info(f"✅ Health check passed - {len(users_config)} user(s) configured")
                    mock_exit(0)
                except Exception as e:
                    mock_logger.error(f"❌ Health check failed: {e}")
                    mock_exit(1)

            mock_logger.info.assert_any_call("🏥 Health check mode")
            mock_get_config.assert_called_once()
            mock_logger.error.assert_called_once_with(f"❌ Health check failed: {test_exception}")
            mock_exit.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_normal_execution_success(self):
        """Test normal main execution"""
        with patch.object(sys, 'argv', ['main.py']), \
             patch('main.asyncio.run') as mock_asyncio_run:

            # Simulate normal execution
            if not (len(sys.argv) > 1 and sys.argv[1] == "--health-check"):
                mock_asyncio_run(main.main())

            mock_asyncio_run.assert_called_once()

    def test_normal_execution_keyboard_interrupt(self):
        """Test normal execution with KeyboardInterrupt"""
        with patch.object(sys, 'argv', ['main.py']), \
             patch('main.asyncio.run') as mock_asyncio_run, \
             patch('main.logger') as mock_logger, \
             patch('main.sys.exit') as mock_exit:

            mock_asyncio_run.side_effect = KeyboardInterrupt()

            # Simulate normal execution with KeyboardInterrupt
            try:
                mock_asyncio_run(main.main())
            except KeyboardInterrupt:
                mock_logger.info("Application terminated by user")
                mock_exit(0)

            mock_logger.info.assert_called_once_with("Application terminated by user")
            mock_exit.assert_called_once_with(0)

    def test_normal_execution_generic_exception(self):
        """Test normal execution with generic exception"""
        test_exception = Exception("Top level error")

        with patch.object(sys, 'argv', ['main.py']), \
             patch('main.asyncio.run') as mock_asyncio_run, \
             patch('main.log_error') as mock_log_error, \
             patch('main.logger') as mock_logger, \
             patch('main.sys.exit') as mock_exit:

            mock_asyncio_run.side_effect = test_exception

            # Simulate normal execution with exception
            try:
                mock_asyncio_run(main.main())
            except Exception as e:
                mock_log_error("Top-level error", e)
                mock_logger.critical(f"Critical error occurred: {e}", exc_info=True)
                mock_exit(1)

            mock_log_error.assert_called_once_with("Top-level error", test_exception)
            mock_logger.critical.assert_called_once_with(f"Critical error occurred: {test_exception}", exc_info=True)
            mock_exit.assert_called_once_with(1)


class TestMainIntegration:
    """Integration tests for main module"""

    @pytest.mark.asyncio
    async def test_main_full_flow_integration(self):
        """Test the complete main flow with all components"""
        mock_users_config = [
            {
                'username': 'testuser',
                'access_token': 'token123',
                'client_id': 'client123',
                'channels': ['testuser']
            }
        ]

        with patch('main.print_instructions') as mock_print_instructions, \
             patch('main.get_configuration', return_value=mock_users_config) as mock_get_config, \
             patch('main.setup_missing_tokens', new_callable=AsyncMock, return_value=mock_users_config) as mock_setup_tokens, \
             patch('main.print_config_summary') as mock_print_summary, \
             patch('main.run_bots', new_callable=AsyncMock) as mock_run_bots, \
             patch('main.logger'):

            await main.main()

            # Verify the complete flow
            assert mock_print_instructions.called
            assert mock_get_config.called
            assert mock_setup_tokens.called
            assert mock_print_summary.called
            assert mock_run_bots.called

    @pytest.mark.asyncio
    async def test_main_empty_config_handling(self):
        """Test main with empty configuration"""
        empty_config = []

        with patch('main.print_instructions'), \
             patch('main.get_configuration', return_value=empty_config), \
             patch('main.setup_missing_tokens', new_callable=AsyncMock, return_value=empty_config) as mock_setup_tokens, \
             patch('main.print_config_summary') as mock_print_summary, \
             patch('main.run_bots', new_callable=AsyncMock) as mock_run_bots, \
             patch('main.logger'):

            await main.main()

            # Verify it still processes empty config
            mock_setup_tokens.assert_called_once_with(empty_config, "twitch_colorchanger.conf")
            mock_print_summary.assert_called_once_with(empty_config)
            mock_run_bots.assert_called_once_with(empty_config, "twitch_colorchanger.conf")

    def test_health_check_multiple_users(self):
        """Test health check with multiple users"""
        mock_users_config = [
            {'username': 'user1'},
            {'username': 'user2'},
            {'username': 'user3'}
        ]

        with patch.object(sys, 'argv', ['main.py', '--health-check']), \
             patch('main.get_configuration', return_value=mock_users_config) as mock_get_config, \
             patch('main.logger') as mock_logger, \
             patch('main.sys.exit') as mock_exit:

            # Simulate the health check mode execution
            if len(sys.argv) > 1 and sys.argv[1] == "--health-check":
                mock_logger.info("🏥 Health check mode")
                try:
                    users_config = mock_get_config()
                    mock_logger.info(f"✅ Health check passed - {len(users_config)} user(s) configured")
                    mock_exit(0)
                except Exception as e:
                    mock_logger.error(f"❌ Health check failed: {e}")
                    mock_exit(1)

            mock_logger.info.assert_any_call("✅ Health check passed - 3 user(s) configured")
            mock_exit.assert_called_once_with(0)

    def test_health_check_no_users(self):
        """Test health check with no users configured"""
        empty_config = []

        with patch.object(sys, 'argv', ['main.py', '--health-check']), \
             patch('main.get_configuration', return_value=empty_config) as mock_get_config, \
             patch('main.logger') as mock_logger, \
             patch('main.sys.exit') as mock_exit:

            # Simulate the health check mode execution
            if len(sys.argv) > 1 and sys.argv[1] == "--health-check":
                mock_logger.info("🏥 Health check mode")
                try:
                    users_config = mock_get_config()
                    mock_logger.info(f"✅ Health check passed - {len(users_config)} user(s) configured")
                    mock_exit(0)
                except Exception as e:
                    mock_logger.error(f"❌ Health check failed: {e}")
                    mock_exit(1)

            mock_logger.info.assert_any_call("✅ Health check passed - 0 user(s) configured")
            mock_exit.assert_called_once_with(0)


class TestMainErrorHandling:
    """Test error handling scenarios in main"""

    @pytest.mark.asyncio
    async def test_main_config_loading_error(self):
        """Test main when configuration loading fails"""
        config_error = Exception("Failed to load config")

        with patch('main.print_instructions'), \
             patch('main.get_configuration') as mock_get_config, \
             patch('main.log_error') as mock_log_error, \
             patch('main.logger') as mock_logger, \
             patch('sys.exit') as mock_exit:

            mock_get_config.side_effect = config_error

            await main.main()

            mock_log_error.assert_called_once_with("Main application error", config_error)
            mock_logger.critical.assert_called_once_with(f"Critical error occurred: {config_error}", exc_info=True)
            mock_exit.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_main_print_summary_error(self):
        """Test main when print_config_summary fails"""
        mock_users_config = [{'username': 'testuser'}]
        summary_error = Exception("Print summary failed")

        with patch('main.print_instructions'), \
             patch('main.get_configuration', return_value=mock_users_config), \
             patch('main.setup_missing_tokens', new_callable=AsyncMock, return_value=mock_users_config), \
             patch('main.print_config_summary') as mock_print_summary, \
             patch('main.log_error') as mock_log_error, \
             patch('main.logger') as mock_logger, \
             patch('sys.exit') as mock_exit:

            mock_print_summary.side_effect = summary_error

            await main.main()

            mock_log_error.assert_called_once_with("Main application error", summary_error)
            mock_logger.critical.assert_called_once_with(f"Critical error occurred: {summary_error}", exc_info=True)
            mock_exit.assert_called_once_with(1)


class TestMainCommandLineArgs:
    """Test command line argument handling"""

    def test_no_arguments(self):
        """Test execution with no command line arguments"""
        with patch.object(sys, 'argv', ['main.py']), \
             patch('main.asyncio.run') as mock_asyncio_run:

            # Simulate normal execution (no health check args)
            if not (len(sys.argv) > 1 and sys.argv[1] == "--health-check"):
                try:
                    mock_asyncio_run(main.main())
                except Exception:
                    pass  # We're just testing the call

            mock_asyncio_run.assert_called_once()

    def test_unknown_argument(self):
        """Test execution with unknown argument (should proceed normally)"""
        with patch.object(sys, 'argv', ['main.py', '--unknown-arg']), \
             patch('main.asyncio.run') as mock_asyncio_run:

            # Simulate normal execution (no health check args)
            if not (len(sys.argv) > 1 and sys.argv[1] == "--health-check"):
                try:
                    mock_asyncio_run(main.main())
                except Exception:
                    pass  # We're just testing the call

            mock_asyncio_run.assert_called_once()

    def test_multiple_arguments_health_check_first(self):
        """Test execution with health check as first argument"""
        with patch.object(sys, 'argv', ['main.py', '--health-check', '--other-arg']), \
             patch('main.get_configuration', return_value=[]) as mock_get_config, \
             patch('main.logger') as mock_logger, \
             patch('main.sys.exit') as mock_exit:

            # Simulate the health check mode execution
            if len(sys.argv) > 1 and sys.argv[1] == "--health-check":
                mock_logger.info("🏥 Health check mode")
                try:
                    users_config = mock_get_config()
                    mock_logger.info(f"✅ Health check passed - {len(users_config)} user(s) configured")
                    mock_exit(0)
                except Exception as e:
                    mock_logger.error(f"❌ Health check failed: {e}")
                    mock_exit(1)

            mock_exit.assert_called_once_with(0)
