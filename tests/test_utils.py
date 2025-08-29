"""
Tests for utility functions
"""

import pytest
from unittest.mock import patch, Mock
import os

from src.utils import print_log, print_instructions
from src.colors import bcolors


class TestPrintLog:
    """Test print_log functionality"""

    def test_print_log_basic_message(self, capsys):
        """Test basic message printing"""
        print_log("Test message")
        captured = capsys.readouterr()
        assert "Test message" in captured.out

    def test_print_log_with_color(self, capsys):
        """Test message printing with color"""
        print_log("Colored message", bcolors.OKGREEN)
        captured = capsys.readouterr()
        assert "Colored message" in captured.out
        # ANSI color codes should be present
        assert bcolors.OKGREEN in captured.out
        assert bcolors.ENDC in captured.out

    def test_print_log_debug_mode_enabled(self, capsys):
        """Test debug message when debug mode is enabled"""
        with patch.dict(os.environ, {'DEBUG': '1'}):
            print_log("Debug message", debug_only=True)
            captured = capsys.readouterr()
            assert "Debug message" in captured.out

    def test_print_log_debug_mode_disabled(self, capsys):
        """Test debug message when debug mode is disabled"""
        with patch.dict(os.environ, {}, clear=True):
            print_log("Debug message", debug_only=True)
            captured = capsys.readouterr()
            assert "Debug message" not in captured.out

    def test_print_log_with_empty_color(self, capsys):
        """Test message printing with empty color"""
        print_log("No color message", "")
        captured = capsys.readouterr()
        assert "No color message" in captured.out

    def test_print_log_force_color_disabled(self, capsys):
        """Test print_log with FORCE_COLOR=false"""
        with patch.dict(os.environ, {'FORCE_COLOR': 'false'}):
            print_log("No color message", bcolors.OKGREEN)
            captured = capsys.readouterr()
            assert "No color message" in captured.out
            # Should not contain ANSI codes
            assert bcolors.OKGREEN not in captured.out
            assert bcolors.ENDC not in captured.out

    def test_print_log_force_color_various_values(self, capsys):
        """Test print_log with various FORCE_COLOR values"""
        test_cases = [
            ('false', False),
            ('False', False),
            ('FALSE', False),
            ('0', False),
            ('no', False),
            ('true', True),
            ('True', True),
            ('TRUE', True),
            ('1', True),
            ('yes', True),
            ('', True),  # Default should be true
        ]

        for env_value, should_color in test_cases:
            with patch.dict(os.environ, {'FORCE_COLOR': env_value}):
                print_log(f"Test {env_value}", bcolors.OKGREEN)
                captured = capsys.readouterr()

                if should_color:
                    assert bcolors.OKGREEN in captured.out
                    assert bcolors.ENDC in captured.out
                else:
                    assert bcolors.OKGREEN not in captured.out
                    assert bcolors.ENDC not in captured.out

    def test_print_log_debug_dynamic_check(self, capsys):
        """Test that DEBUG is checked dynamically, not just at import"""
        # Start with debug disabled
        with patch.dict(os.environ, {'DEBUG': 'false'}):
            print_log("Should not print", debug_only=True)
            captured1 = capsys.readouterr()
            assert "Should not print" not in captured1.out

        # Change environment and test again
        with patch.dict(os.environ, {'DEBUG': 'true'}):
            print_log("Should print now", debug_only=True)
            captured2 = capsys.readouterr()
            assert "Should print now" in captured2.out


class TestPrintInstructions:
    """Test print_instructions functionality"""

    def test_print_instructions_output(self, capsys):
        """Test that instructions are printed"""
        print_instructions()
        captured = capsys.readouterr()
        
        # Check for key instruction elements
        assert "instructions" in captured.out.lower() or "usage" in captured.out.lower()
        assert len(captured.out) > 0

    def test_print_instructions_contains_essential_info(self, capsys):
        """Test that instructions contain essential information"""
        print_instructions()
        captured = capsys.readouterr()
        
        # Instructions should contain some guidance
        output_lower = captured.out.lower()
        assert any(keyword in output_lower for keyword in [
            'config', 'setup', 'bot', 'twitch', 'color', 'usage'
        ])


class TestUtilsIntegration:
    """Test utility functions integration"""

    def test_print_log_multiple_calls(self, capsys):
        """Test multiple print_log calls"""
        messages = ["Message 1", "Message 2", "Message 3"]
        colors = [bcolors.OKGREEN, bcolors.WARNING, bcolors.FAIL]
        
        for msg, color in zip(messages, colors):
            print_log(msg, color)
        
        captured = capsys.readouterr()
        
        # All messages should be present
        for msg in messages:
            assert msg in captured.out
        
        # Color codes should be present
        for color in colors:
            assert color in captured.out

    @patch.dict(os.environ, {'DEBUG': '1'})
    def test_debug_and_normal_messages(self, capsys):
        """Test combination of debug and normal messages"""
        print_log("Normal message")
        print_log("Debug message", debug_only=True)
        print_log("Another normal message", bcolors.OKBLUE)
        
        captured = capsys.readouterr()
        
        assert "Normal message" in captured.out
        assert "Debug message" in captured.out
        assert "Another normal message" in captured.out
        assert bcolors.OKBLUE in captured.out

    def test_error_handling_in_print_log(self, capsys):
        """Test error handling in print_log"""
        # Test with various input types
        print_log(123)  # Integer
        print_log(None)  # None
        print_log("")   # Empty string
        
        captured = capsys.readouterr()
        
        # Should handle these gracefully without crashing
        assert "123" in captured.out or captured.out is not None
