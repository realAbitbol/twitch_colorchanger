# Testing Infrastructure for Twitch ColorChanger Bot

This directory contains the comprehensive test suite for the Twitch ColorChanger Bot with **100% test coverage** across all modules.

## Test Structure

- `conftest.py` - Pytest configuration and shared fixtures
- `test_*.py` - Individual test modules (551 tests total)
- `fixtures/` - Test data and mock responses
- `integration/` - Integration tests

## Test Coverage Statistics

### Overall Coverage

100% (1,587 lines, 440 branches)

### Module Coverage

- `main.py`: 100% (24 lines)
- `src/bot.py`: 100% (358 lines, 102 branches) - 103 tests
- `src/bot_manager.py`: 100% (208 lines, 54 branches) - 79 tests  
- `src/colors.py`: 100% (48 lines, 16 branches) - 70 tests
- `src/config.py`: 100% (252 lines, 62 branches) - 73 tests
- `src/config_validator.py`: 100% (82 lines, 42 branches) - 44 tests
- `src/config_watcher.py`: 100% (91 lines, 18 branches) - 21 tests
- `src/device_flow.py`: 100% (102 lines, 28 branches) - 27 tests
- `src/error_handling.py`: 100% (21 lines, 4 branches) - 22 tests
- `src/logger.py`: 100% (66 lines, 20 branches) - 33 tests
- `src/rate_limiter.py`: 100% (125 lines, 38 branches) - 35 tests
- `src/simple_irc.py`: 100% (163 lines, 46 branches) - 49 tests
- `src/utils.py`: 100% (38 lines, 6 branches) - 11 tests
- `src/watcher_globals.py`: 100% (9 lines, 4 branches) - 7 tests
- Integration tests: 6 tests

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
