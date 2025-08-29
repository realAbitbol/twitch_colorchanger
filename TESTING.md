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
├── conftest.py              # Pytest configuration and shared fixtures
├── fixtures/
│   ├── sample_configs.py    # Test configuration data
│   └── api_responses.py     # Mock API responses
├── test_colors.py           # Color module tests (36 tests, 94% coverage)
├── test_config.py           # Configuration management tests
├── test_bot.py              # Bot functionality tests
└── integration/
    └── test_twitch_integration.py  # Integration tests
```

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

- **Minimum**: 80% overall coverage
- **Target**: 90%+ overall coverage
- **Critical modules**: 95%+ coverage (colors, config, bot)

### Current Coverage Status
- `src/colors.py`: 94% coverage (50/53 lines)
- Missing coverage on edge cases in color generation

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
