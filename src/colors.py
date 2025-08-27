"""
Color definitions and utilities for console output
"""

import random


class bcolors:
    """ANSI color codes for console output"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    PURPLE = '\033[95m'


def get_twitch_colors():
    """Get list of available Twitch preset colors"""
    return [
        'Red', 'Blue', 'Green', 'FireBrick', 'Coral', 'YellowGreen',
        'OrangeRed', 'SeaGreen', 'GoldenRod', 'Chocolate', 'CadetBlue',
        'DodgerBlue', 'HotPink', 'BlueViolet', 'SpringGreen'
    ]


def generate_random_hex_color():
    """Generate random hex color for Prime/Turbo users"""
    hue = random.randint(0, 359)
    saturation = random.randint(60, 100)
    lightness = random.randint(35, 75)
    c = (1 - abs(2 * lightness/100 - 1)) * saturation/100
    x = c * (1 - abs((hue / 60) % 2 - 1))
    m = lightness/100 - c/2
    
    if 0 <= hue < 60:
        r, g, b = c, x, 0
    elif 60 <= hue < 120:
        r, g, b = x, c, 0
    elif 120 <= hue < 180:
        r, g, b = 0, c, x
    elif 180 <= hue < 240:
        r, g, b = 0, x, c
    elif 240 <= hue < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    
    r = int((r + m) * 255)
    g = int((g + m) * 255)
    b = int((b + m) * 255)
    
    return f"#{r:02x}{g:02x}{b:02x}"
