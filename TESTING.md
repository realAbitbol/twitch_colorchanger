# Testing Guide

This project uses pytest for comprehensive testing with coverage reporting and quality tools.

## Quick Start

### Run all tests
```bash
make test
```

### Run tests with coverage
```bash
make test-cov
```

### Format and lint code
```bash
make format
make lint
```

## Testing Structure

```
tests/
├── conftest.py                      # Pytest configuration and shared fixtures
├── fixtures/
│   ├── sample_configs.py           # Test configuration data
│   └── api_responses.py            # Mock API responses
├── test_bot.py                     # Bot functionality tests (103 tests)
├── test_bot_manager.py             # Bot manager tests (79 tests)
├── test_colors.py                  # Color module tests (70 tests)
├── test_config.py                  # Configuration management tests (73 tests)
├── test_config_validator.py        # Config validation tests (44 tests)
├── test_config_watcher.py          # Live config reload tests (21 tests)
├── test_device_flow.py             # OAuth device flow tests (27 tests)
├── test_error_handling.py          # Error handling tests (22 tests)
├── test_logger.py                  # Logger tests (33 tests)
├── test_main.py                    # Main entry point tests (20 tests)
├── test_rate_limiter.py            # Rate limiting tests (35 tests)
├── test_simple_irc.py              # IRC client tests (49 tests)
├── test_utils.py                   # Utility function tests (11 tests)
├── test_watcher_globals.py         # Global watcher tests (7 tests)
└── integration/
    └── test_integration.py         # Integration tests (6 tests)
```

**Total Test Coverage**: 551 tests across all modules with 100% line and branch coverage

## Available Make Targets

| Target | Description |
|--------|-------------|
| `make test` | Run all tests |
| `make test-cov` | Run tests with coverage report |
| `make test-html` | Generate HTML coverage report |
| `make format` | Format code with black and isort |
| `make lint` | Run all linting tools |
| `make check` | Run tests, coverage, and linting |
| `make clean` | Clean testing artifacts |

## Individual Tool Usage

### Testing
```bash
# Run specific test file
pytest tests/test_colors.py

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src

# Generate HTML coverage report
pytest --cov=src --cov-report=html
```

### Code Quality
```bash
# Format code
black src/ tests/
isort src/ tests/

# Type checking
mypy src/

# Linting
flake8 src/ tests/

# Security check
bandit -r src/

# Dependency vulnerability check
safety check
```

## Coverage Goals

- **Current Achievement**: 100% overall coverage ✅
- **Total Lines**: 1,587 lines covered (main.py + src/)
- **Total Branches**: 440 branches covered
- **Test Count**: 551 tests passing

### Current Coverage Status (100% across all modules)
- `main.py`: 100% coverage (24/24 lines)
- `src/bot.py`: 100% coverage (358/358 lines, 102/102 branches)
- `src/bot_manager.py`: 100% coverage (208/208 lines, 54/54 branches)
- `src/colors.py`: 100% coverage (48/48 lines, 16/16 branches)
- `src/config.py`: 100% coverage (252/252 lines, 62/62 branches)
- `src/config_validator.py`: 100% coverage (82/82 lines, 42/42 branches)
- `src/config_watcher.py`: 100% coverage (91/91 lines, 18/18 branches)
- `src/device_flow.py`: 100% coverage (102/102 lines, 28/28 branches)
- `src/error_handling.py`: 100% coverage (21/21 lines, 4/4 branches)
- `src/logger.py`: 100% coverage (66/66 lines, 20/20 branches)
- `src/rate_limiter.py`: 100% coverage (125/125 lines, 38/38 branches)
- `src/simple_irc.py`: 100% coverage (163/163 lines, 46/46 branches)
- `src/utils.py`: 100% coverage (38/38 lines, 6/6 branches)
- `src/watcher_globals.py`: 100% coverage (9/9 lines, 4/4 branches)

## Test Categories

### Unit Tests
- Individual function testing
- Isolated component validation
- Mock external dependencies

### Integration Tests
- Multi-component interaction
- API integration testing
- End-to-end workflows

### Performance Tests
- Color generation speed
- Memory usage validation
- Concurrent operation testing

## Configuration

All tool configurations are centralized in `pyproject.toml`:

- **pytest**: Async support, coverage settings
- **coverage**: Branch coverage, exclusions
- **black**: Code formatting rules
- **isort**: Import sorting configuration
- **mypy**: Type checking settings
- **bandit**: Security check configuration

## Continuous Integration

This testing setup is designed for CI/CD integration:

1. Install dependencies: `pip install -r requirements-dev.txt`
2. Run quality checks: `make check`
3. Generate reports: `make test-html`

## Adding New Tests

1. Create test file in `tests/` directory
2. Import required fixtures from `conftest.py`
3. Use descriptive test names: `test_feature_when_condition_then_outcome`
4. Add docstrings for complex test logic
5. Use parametrize for multiple test cases
6. Mock external dependencies appropriately

## Debugging Tests

```bash
# Run with debug output
pytest -s -vv tests/test_colors.py

# Run specific test
pytest tests/test_colors.py::test_generate_random_color

# Drop into debugger on failure
pytest --pdb tests/test_colors.py

# Run last failed tests
pytest --lf
```

## Performance Considerations

- Tests should complete in under 10 seconds total
- Mock external API calls to avoid network dependencies
- Use fixtures for expensive setup operations
- Consider parallel execution for large test suites

## Best Practices

1. **Test Naming**: Use descriptive names that explain the scenario
2. **Isolation**: Each test should be independent and repeatable
3. **Coverage**: Aim for both line and branch coverage
4. **Mocking**: Mock external dependencies consistently
5. **Assertions**: Use specific assertions with clear failure messages
6. **Documentation**: Add docstrings for complex test logic
