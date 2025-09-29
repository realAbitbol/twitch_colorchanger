# Testing Infrastructure and Guidelines

This document provides comprehensive instructions for writing, running, and maintaining tests for the Twitch Color Changer application.

## Testing Strategy

The testing strategy follows a pyramid approach with three levels:

1. **Unit Tests** (80% of tests): Test individual functions/classes in isolation
2. **Integration Tests** (15% of tests): Test interactions between components
3. **End-to-End Tests** (5% of tests): Test complete application workflows

### Requirements

- **Coverage**: Minimum 95% code coverage required
- **Performance**: Entire test suite must complete in ≤60 seconds
- **Quality**: 0 failed tests, 0 pytest warnings
- **Timeout**: Individual tests timeout at 10 seconds

## Project Structure

```
tests/
├── fixtures/           # Test data and mock objects
│   ├── __init__.py
│   ├── twitch_api_fixtures.py
│   ├── config_fixtures.py
│   └── token_fixtures.py
├── templates/          # Test templates for different test types
│   ├── __init__.py
│   ├── unit_test_template.py
│   ├── integration_test_template.py
│   └── e2e_test_template.py
├── unit/              # Unit tests (one file per module)
└── README.md         # This file
```

**Note**: `integration/` and `e2e/` directories are planned for future phases.

## Running Tests

### Basic Commands

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test file
pytest tests/unit/test_specific_module.py

# Run tests matching pattern
pytest -k "test_name_pattern"

# Run tests with verbose output
pytest -v

# Run tests with coverage report
pytest --cov=src --cov-report=html
```

### Test Categories

```bash
# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest -m integration

# Run only e2e tests
pytest -m e2e

# Run tests for specific module
pytest tests/unit/test_auth_token.py
```

## Writing Tests

### General Guidelines

1. **Use descriptive test names**: `test_should_handle_valid_token_refresh`
2. **Follow AAA pattern**: Arrange, Act, Assert
3. **One assertion per test** when possible
4. **Use fixtures** for reusable test data
5. **Mock external dependencies** appropriately
6. **Test both success and failure cases**
7. **Test edge cases and boundary conditions**

### Using Fixtures

Import and use fixtures from `tests/fixtures/`:

```python
from tests.fixtures.twitch_api_fixtures import MOCK_COLOR_CHANGE_MESSAGE
from tests.fixtures.config_fixtures import get_mock_config_as_dict
from tests.fixtures.token_fixtures import get_mock_token

def test_example():
    config = get_mock_config_as_dict("full")
    token = get_mock_token("valid")
    # Use fixtures in test
```

### Test Templates

Use the provided templates in `tests/templates/` as starting points:

- `unit_test_template.py`: For isolated unit tests
- `integration_test_template.py`: For component interaction tests
- `e2e_test_template.py`: For full application flow tests

### Async Testing

For async functions, use `@pytest.mark.asyncio`:

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await async_function_under_test()
    assert result == expected_value
```

### Mocking Guidelines

1. **Mock external APIs**: Use `unittest.mock` or `pytest-mock`
2. **Mock time-dependent functions**: Use `freezegun` for datetime mocking
3. **Mock network calls**: Use `aiohttp` test client or mock responses
4. **Don't mock everything**: Test real logic, mock only external dependencies

```python
from unittest.mock import patch, Mock

@patch('src.external_module.ExternalAPI.call')
def test_with_mock(mock_api_call):
    mock_api_call.return_value = mock_response
    result = function_under_test()
    assert result.success
    mock_api_call.assert_called_once()
```

## Test Organization

### Unit Tests (`tests/unit/`)

- One test file per source module: `test_module_name.py`
- Test classes: `TestClassName`
- Test methods: `test_method_name_scenario`

Example:
```
tests/unit/
├── test_auth_token.py
├── test_config.py
├── test_chat.py
└── ...
```

### Integration Tests (`tests/integration/`)

- Test component interactions
- Use `@pytest.mark.integration` decorator
- May require setup/teardown of multiple components

### E2E Tests (`tests/e2e/`)

- Test complete workflows
- Use `@pytest.mark.e2e` decorator
- May use temporary files/databases
- Should be minimal but comprehensive

## Best Practices

### Code Quality

- **No warnings**: Fix all pytest warnings before committing
- **Clean code**: Follow PEP 8, use type hints
- **Documentation**: Document complex test scenarios
- **Maintainability**: Keep tests simple and focused

### Performance

- **Fast tests**: Individual tests should complete in <1 second
- **Parallel execution**: Tests should be runnable in parallel
- **Resource cleanup**: Always clean up resources in teardown
- **Minimal fixtures**: Reuse fixtures to avoid duplication

### Reliability

- **Deterministic**: Tests should produce consistent results
- **Isolated**: No test should depend on others
- **Idempotent**: Running tests multiple times should be safe
- **Environment agnostic**: Tests should work in any environment

## Component-Specific Testing

### Authentication Token Testing

- Test token validation logic
- Test refresh mechanisms
- Mock HTTP calls to Twitch API
- Test expiration handling

### Configuration Testing

- Test config loading from files
- Test validation logic
- Test saving/updating configs
- Test error handling for invalid configs

### Chat/WebSocket Testing

- Test connection establishment
- Test message handling
- Test reconnection logic
- Mock WebSocket connections

### Color Service Testing

- Test color validation
- Test color change logic
- Test API interactions
- Test error scenarios

## Debugging Tests

### Common Issues

1. **Async test failures**: Ensure proper `await` usage
2. **Mock not working**: Check import paths and patch targets
3. **Fixture not found**: Verify fixture location and imports
4. **Coverage issues**: Check which lines aren't covered

### Debugging Tools

```bash
# Debug specific test
pytest tests/unit/test_example.py::TestClass::test_method -s

# Show coverage for specific file
pytest --cov=src/specific_module --cov-report=html

# Profile slow tests
pytest --durations=10
```

## Continuous Integration

Tests are automatically run in CI with:

- Coverage reporting
- Performance monitoring
- Quality gate checks
- Failure notifications

### Pre-commit Checks

Before committing, ensure:

```bash
make lint      # Code quality checks
make test      # Run test suite
make test-cov  # Coverage check
```

## Maintenance

### Adding New Tests

1. Identify test type (unit/integration/e2e)
2. Use appropriate template
3. Add necessary fixtures
4. Follow naming conventions
5. Update this documentation if needed

### Updating Fixtures

- Keep fixtures in `tests/fixtures/`
- Update fixtures when API contracts change
- Ensure backward compatibility
- Document fixture usage

### Refactoring Tests

- Tests should be refactored along with code
- Maintain test coverage during refactoring
- Update test documentation
- Run full test suite after changes

## Troubleshooting

### Test Failures

- Check error messages carefully
- Verify mock configurations
- Ensure test isolation
- Check for race conditions in async tests

### Performance Issues

- Profile slow tests with `--durations`
- Optimize fixture creation
- Reduce external API calls
- Use appropriate mocking

### Coverage Gaps

- Identify uncovered code with coverage reports
- Add missing test cases
- Consider if code needs testing or refactoring
- Ensure test quality, not just quantity

## Resources

- [pytest Documentation](https://docs.pytest.org/)
- [unittest.mock Documentation](https://docs.python.org/3/library/unittest.mock.html)
- [Coverage.py Documentation](https://coverage.readthedocs.io/)
- [Async Testing in pytest](https://pytest-asyncio.readthedocs.io/)