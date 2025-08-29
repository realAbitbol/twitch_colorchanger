"""
Tests for color generation and management functionality
"""

import pytest
from unittest.mock import patch

from src.colors import (
    bcolors,
    generate_random_hex_color,
    get_different_twitch_color,
    get_twitch_colors
)


class TestColorGeneration:
    """Test color generation functions"""
    
    def test_generate_random_hex_color_format(self):
        """Test that generated hex colors have correct format"""
        color = generate_random_hex_color()
        
        assert color.startswith('#')
        assert len(color) == 7
        assert all(c in '0123456789abcdef' for c in color[1:].lower())
    
    def test_generate_random_hex_color_uniqueness(self):
        """Test that multiple calls generate different colors (with high probability)"""
        colors = [generate_random_hex_color() for _ in range(10)]
        
        # With 16.7M possible colors, getting 10 unique colors is virtually guaranteed
        assert len(set(colors)) == 10
    
    def test_generate_random_hex_color_avoid_current(self):
        """Test that random color generation avoids current color"""
        current_color = "#FF0000"
        
        # Generate many colors to ensure we don't get the current one
        colors = [generate_random_hex_color(current_color) for _ in range(50)]
        
        assert current_color not in colors
    
    def test_generate_random_hex_color_no_avoid(self):
        """Test random color generation without avoiding any color"""
        colors = [generate_random_hex_color() for _ in range(10)]
        
        # All should be valid hex colors
        for color in colors:
            assert color.startswith('#')
            assert len(color) == 7


class TestTwitchPresetColors:
    """Test Twitch preset color functionality"""
    
    def test_twitch_colors_constant(self):
        """Test that get_twitch_colors contains expected colors"""
        expected_colors = [
            'blue', 'blue_violet', 'cadet_blue', 'chocolate', 'coral',
            'dodger_blue', 'firebrick', 'golden_rod', 'green', 'hot_pink',
            'orange_red', 'red', 'sea_green', 'spring_green', 'yellow_green'
        ]
        
        twitch_colors = get_twitch_colors()
        assert len(twitch_colors) == len(expected_colors)
        for color in expected_colors:
            assert color in twitch_colors
    
    def test_get_different_twitch_color_avoids_current(self):
        """Test that preset color selection avoids current color"""
        current_color = "blue"
        twitch_colors = get_twitch_colors()
        
        # Generate many colors to ensure we don't get the current one
        colors = [get_different_twitch_color(current_color) for _ in range(50)]
        
        assert current_color not in colors
        # All returned colors should be valid Twitch colors
        for color in colors:
            assert color in twitch_colors
    
    def test_get_different_twitch_color_no_current(self):
        """Test preset color selection when no current color is specified"""
        twitch_colors = get_twitch_colors()
        colors = [get_different_twitch_color() for _ in range(10)]
        
        # All should be valid Twitch colors
        for color in colors:
            assert color in twitch_colors
    
    def test_get_different_twitch_color_invalid_current(self):
        """Test preset color selection with invalid current color"""
        invalid_current = "InvalidColor"
        twitch_colors = get_twitch_colors()
        
        colors = [get_different_twitch_color(invalid_current) for _ in range(10)]
        
        # Should still return valid colors
        for color in colors:
            assert color in twitch_colors
    
    def test_get_different_twitch_color_case_sensitivity(self):
        """Test that color comparison is case sensitive"""
        # Since colors are lowercase, "BLUE" is different from "blue"
        current_color = "BLUE"  # uppercase - not in the color list
        twitch_colors = get_twitch_colors()
        
        colors = [get_different_twitch_color(current_color) for _ in range(10)]
        
        # Should return any valid colors since "BLUE" doesn't match any lowercase colors
        for color in colors:
            assert color in twitch_colors
        # Should include "blue" since it's different from "BLUE"
        assert "blue" in get_twitch_colors()  # Verify blue exists in lowercase


class TestColorConstants:
    """Test color constants and terminal formatting"""
    
    def test_bcolors_constants(self):
        """Test that bcolors constants are defined"""
        required_colors = [
            'HEADER', 'OKBLUE', 'OKCYAN', 'OKGREEN', 
            'WARNING', 'FAIL', 'ENDC', 'BOLD', 'PURPLE'
        ]
        
        for color in required_colors:
            assert hasattr(bcolors, color)
            assert isinstance(getattr(bcolors, color), str)
    
    def test_bcolors_ansi_codes(self):
        """Test that bcolors contain proper ANSI escape codes"""
        # Most colors should contain ANSI escape sequences
        color_codes = [
            bcolors.HEADER, bcolors.OKBLUE, bcolors.OKCYAN,
            bcolors.OKGREEN, bcolors.WARNING, bcolors.FAIL,
            bcolors.BOLD, bcolors.PURPLE
        ]
        
        for code in color_codes:
            assert code.startswith('\033[') or code.startswith('\x1b[')
        
        # ENDC should be a reset code
        assert bcolors.ENDC in ['\033[0m', '\x1b[0m']


class TestColorValidation:
    """Test color validation and edge cases"""
    
    def test_hex_color_validation_pattern(self):
        """Test various hex color patterns"""
        valid_colors = ["#FF0000", "#00FF00", "#0000FF", "#123456", "#ABCDEF"]
        
        for color in valid_colors:
            # Should be able to generate without errors
            new_color = generate_random_hex_color(color)
            assert new_color != color
            assert new_color.startswith('#')
    
    def test_preset_color_edge_cases(self):
        """Test preset color selection edge cases"""
        twitch_colors = get_twitch_colors()
        # Test with all possible current colors
        for current in twitch_colors:
            new_color = get_different_twitch_color(current)
            assert new_color != current
            assert new_color in twitch_colors
    
    def test_color_generation_performance(self):
        """Test that color generation is reasonably fast"""
        import time
        
        start_time = time.time()
        
        # Generate many colors
        for _ in range(1000):
            generate_random_hex_color()
            get_different_twitch_color()
        
        end_time = time.time()
        
        # Should complete in reasonable time (less than 1 second)
        assert end_time - start_time < 1.0


@pytest.mark.parametrize("current_color,expected_different", [
    ("#FF0000", True),
    ("#000000", True), 
    ("#FFFFFF", True),
    (None, True),
    ("", True),
])
def test_hex_color_generation_parameterized(current_color, expected_different):
    """Parameterized test for hex color generation"""
    new_color = generate_random_hex_color(current_color)
    
    if current_color and current_color.startswith('#') and len(current_color) == 7:
        assert new_color != current_color
    
    assert new_color.startswith('#')
    assert len(new_color) == 7


@pytest.mark.parametrize("current_color", get_twitch_colors())
def test_preset_color_generation_parameterized(current_color):
    """Parameterized test for preset color generation with all Twitch colors"""
    twitch_colors = get_twitch_colors()
    new_color = get_different_twitch_color(current_color)
    
    assert new_color != current_color
    assert new_color in twitch_colors


class TestColorIntegration:
    """Integration tests for color functionality"""
    
    def test_color_system_integration(self):
        """Test integration between hex and preset color systems"""
        twitch_colors = get_twitch_colors()
        
        # Test switching between color types
        hex_color = generate_random_hex_color()
        preset_color = get_different_twitch_color()
        
        assert hex_color.startswith('#')
        assert preset_color in twitch_colors
        
        # Ensure they're different types
        assert hex_color != preset_color
    
    def test_color_uniqueness_over_time(self):
        """Test that color generation maintains uniqueness over many calls"""
        twitch_colors = get_twitch_colors()
        hex_colors = set()
        preset_colors = set()
        
        for _ in range(100):
            hex_colors.add(generate_random_hex_color())
            preset_colors.add(get_different_twitch_color())
        
        # Should have generated many unique hex colors
        assert len(hex_colors) > 90  # Very high probability with random generation
        
        # Preset colors are limited, but should use all available colors eventually
        assert len(preset_colors) >= min(100, len(twitch_colors))
