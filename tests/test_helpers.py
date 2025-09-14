
from src.utils.helpers import emit_startup_instructions, format_duration

# Tests for format_duration

def test_format_duration_none():
    """Test format_duration with None input."""
    assert format_duration(None) == "unknown"


def test_format_duration_negative():
    """Test format_duration with negative value."""
    assert format_duration(-1) == "-1s"


def test_format_duration_zero():
    """Test format_duration with zero."""
    assert format_duration(0) == "0s"


def test_format_duration_seconds_only():
    """Test format_duration with seconds only (< 60)."""
    assert format_duration(59) == "59s"


def test_format_duration_minutes_seconds():
    """Test format_duration with minutes and seconds."""
    assert format_duration(65) == "1m 5s"


def test_format_duration_large_value():
    """Test format_duration with large value including days."""
    # 2 days, 1 hour, 1 minute, 5 seconds
    total_seconds = 86400 * 2 + 3600 + 60 + 5
    assert format_duration(total_seconds) == "2d 1h 1m 5s"


# Tests for emit_startup_instructions

def test_emit_startup_instructions_output(capsys):
    """Test that emit_startup_instructions prints the expected output."""
    emit_startup_instructions()
    captured = capsys.readouterr()
    expected_output = (
        "📘 Instructions\n"
        "🪜 Setup step 1: Create a Twitch application: https://dev.twitch.tv/console/apps\n"
        "🪜 Setup step 2: Set OAuth Redirect URL to: https://twitchtokengenerator.com\n"
        "🪜 Setup step 3: Copy your Client ID and Client Secret\n"
        "⚙️ Automatic configuration\n"
        "👉 Copy twitch_colorchanger.conf.sample to twitch_colorchanger.conf\n"
        "👉 Add username, client_id, client_secret\n"
        "👉 Run the bot; it handles token authorization automatically\n"
        "👉 Follow displayed URL and enter the code when prompted\n"
        "📝 Manual configuration\n"
        "👉 Generate tokens: https://twitchtokengenerator.com\n"
        "👉 Select scopes: chat:read, user:manage:chat_color\n"
        "👉 Save Access & Refresh Tokens in config file\n"
        "ℹ️ Features\n"
        "👉 Monitors your chat messages\n"
        "👉 Changes username color after each message\n"
        "👉 Supports preset Twitch and random hex colors\n"
        "👉 Handles multiple users simultaneously\n"
        "👉 Auto-refreshes tokens to minimize re-authorization\n"
        "👉 type 'ccd' to disable or 'cce' to enable in any joined channel.\n"
        "👉 type 'ccc <color>' to manually change color (preset or hex).\n"
        "🔒 Security notice : Remember to never share your client id, client secret or your tokens!\n"
    )
    assert captured.out == expected_output


def test_emit_startup_instructions_no_errors():
    """Test that emit_startup_instructions runs without errors."""
    # This test ensures the function can be called without raising exceptions
    emit_startup_instructions()
