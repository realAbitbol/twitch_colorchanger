from src.constants import _get_env_int


def test_get_env_int_valid_positive_integer(monkeypatch):
    """Test parsing a valid positive integer from environment variable."""
    monkeypatch.setenv("TEST_VAR", "123")
    assert _get_env_int("TEST_VAR", 999) == 123


def test_get_env_int_valid_negative_integer(monkeypatch):
    """Test parsing a valid negative integer from environment variable."""
    monkeypatch.setenv("TEST_VAR", "-456")
    assert _get_env_int("TEST_VAR", 999) == -456


def test_get_env_int_invalid_string(monkeypatch):
    """Test handling of invalid string value in environment variable."""
    monkeypatch.setenv("TEST_VAR", "abc")
    assert _get_env_int("TEST_VAR", 999) == 999


def test_get_env_int_empty_string(monkeypatch):
    """Test handling of empty string value in environment variable."""
    monkeypatch.setenv("TEST_VAR", "")
    assert _get_env_int("TEST_VAR", 999) == 999


def test_get_env_int_float_string(monkeypatch):
    """Test handling of float string value in environment variable."""
    monkeypatch.setenv("TEST_VAR", "3.14")
    assert _get_env_int("TEST_VAR", 999) == 999
