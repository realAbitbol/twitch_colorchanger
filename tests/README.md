# Testing Infrastructure for Twitch ColorChanger Bot

This directory contains the test suite for the Twitch ColorChanger Bot.

## Test Structure

- `conftest.py` - Pytest configuration and shared fixtures
- `test_*.py` - Individual test modules
- `fixtures/` - Test data and mock responses
- `integration/` - Integration tests

## Running Tests

```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html --cov-report=term

# Run specific test file
pytest tests/test_bot.py -v

# Run with debugging
pytest -s -vv tests/test_config.py::test_load_config
```

## Test Categories

1. **Unit Tests**: Test individual functions and methods in isolation
2. **Integration Tests**: Test component interactions
3. **API Tests**: Test Twitch API interactions with mocking
4. **Configuration Tests**: Test config loading, validation, and management
5. **Bot Lifecycle Tests**: Test bot startup, shutdown, and error handling

## Mocking Strategy

- **aiohttp**: Mock HTTP requests to Twitch API
- **IRC connections**: Mock socket connections
- **File system**: Mock config file operations
- **Time**: Mock datetime for token expiry testing
