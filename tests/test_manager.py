"""Tests for src/manager/__init__.py."""

import pytest

from src.manager import __all__


def test_import_manager_module():
    """Test successful import of the manager module without errors."""
    # The module should import without raising any exceptions
    assert __all__ == []
