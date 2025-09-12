# Twitch Color Changer Simplification Plan

## Overview

This plan outlines the comprehensive simplification of the Twitch Color Changer application to remove overengineering and make it lean. The primary goals are:

- Remove IRC support entirely (bot now uses only EventSub)
- Simplify logging from structured event-based to standard Python logging
- Eliminate unnecessary abstractions and complex components
- Retain core functionality: deviceflow onboarding, token persistence, multi-user support, and Docker support

## Current Architecture Analysis

The application currently has:

- Dual chat backends (IRC and EventSub)
- Complex structured logging with event templates
- Over-engineered rate limiting with multiple strategies
- Adaptive scheduler with complex logic
- Health monitoring and maintenance loops
- Multiple abstraction layers

## Retained Features

- Device flow authentication (`src/token/device_flow.py`)
- Token persistence and management (`src/token/manager.py`)
- Multi-user configuration support (`src/config/`)
- Docker containerization (`Dockerfile`, `docker-compose.yml-sample`)

## Implementation Guidelines

To ensure complete execution and avoid leaving tasks half-finished:

### Completion Requirements

- **Each phase must be fully completed before moving to the next**
- **All references to removed components must be eliminated** - use grep/search to find and remove all imports, calls, and references
- **Tests must pass after each phase** - run the full test suite and fix any failures immediately
- **No dead code left behind** - remove unused imports, variables, and functions after each change
- **Logging refactor must be 100% complete** - every `logger.log_event()` call must be replaced with standard logging, no exceptions
- **Prohibit shims during refactoring** - do not use temporary shims, adapters, or compatibility layers; aim for direct, pure code changes without introducing useless bloat

### Validation Steps After Each Phase

1. Run `.venv/bin/python -m pytest` to ensure all tests pass
2. Run `.venv/bin/python -m mypy src/` for type checking
3. Run `.venv/bin/ruff check --fix src/` for linting
4. Verify application starts and basic functionality works
5. Check that removed directories/files are actually deleted

### Logging Refactor Specific Instructions

- **Systematic replacement**: Use search/replace tools to find all `logger.log_event` calls
- **Preserve log levels**: Map event types to appropriate logging levels (info, warning, error, debug)
- **Simplify messages**: Convert structured events to readable log messages
- **Remove event parameters**: Replace event-specific args with standard format strings
- **Update all files**: Check every Python file in src/ for logger usage
- **Test logging output**: Ensure logs are readable and contain necessary information

## Phase 1: IRC Removal

### 1.1 Remove IRC Backend Files

- Delete `src/irc/` directory entirely (contains ~10 files)
- Delete `src/chat/irc_backend.py`
- Remove IRC-related imports and references

### 1.2 Update Chat Backend Factory

- Modify `src/chat/__init__.py` to remove IRC backend creation
- Update `create_chat_backend()` to only support 'eventsub'
- Remove `BackendType.IRC` enum value

### 1.3 Clean Bot Core

- Remove IRC-related code from `src/bot/core.py`:
  - Remove `_determine_backend_type()` method (always use EventSub)
  - Remove IRC-specific error handling
  - Remove legacy IRC attributes (`self.irc`)
  - Simplify connection initialization

### 1.4 Update Configuration

- Remove IRC-related environment variables and config options
- Update documentation to reflect EventSub-only operation

### 1.5 Update Tests

- Remove all IRC-related test files (`tests/test_irc_*.py`)
- Update integration tests to use EventSub only

## Phase 2: Logging Simplification

### 2.1 Replace Event Logger

- Remove `src/logs/` directory entirely
- Replace `BotLogger` with standard Python `logging` module
- Remove event templates and structured logging

### 2.2 Update All Logging Calls

- Replace `logger.log_event()` calls with standard `logging.info()`, `logging.error()`, etc.
- Remove event-specific parameters and templates
- Simplify log messages to be direct and readable

### 2.3 Update Imports

- Remove imports of custom logger throughout codebase
- Use `import logging` instead

## Phase 3: Remove Overengineered Components

### 3.1 Simplify Rate Limiting

- Remove `src/rate/` directory (backoff strategies, retry policies, rate limit headers)
- Implement simple rate limiting directly in API calls
- Use basic exponential backoff for retries

### 3.2 Replace Adaptive Scheduler

- Remove `src/scheduler/` directory
- Replace `AdaptiveScheduler` with simple `asyncio.sleep()` based scheduling
- Remove complex timing logic

### 3.3 Simplify Health Monitoring

- Remove `src/manager/health.py` and `src/manager/task_watchdog.py`
- Remove health check endpoints and status files
- Simplify manager to basic bot lifecycle management

### 3.4 Streamline Application Context

- Remove maintenance loops from `ApplicationContext`
- Remove complex session recycling and rate limiter probing
- Keep only essential shared resources

### 3.5 Remove Unnecessary Abstractions

- Merge `BotPersistenceMixin` into `TwitchColorBot`
- Remove `BotRegistrar` and `BotStats` classes
- Simplify bot initialization and registration

## Phase 4: Code Cleanup and Optimization

### 4.1 Remove Dead Code

- Remove unused imports and variables
- Remove commented-out code
- Remove debug-only features

### 4.2 Simplify Error Handling

- Replace complex error handling with straightforward try/except
- Remove excessive logging in error paths

### 4.3 Optimize Dependencies

- Review `requirements.txt` and remove unused packages
- Update `pyproject.toml` dependencies

## Phase 5: Testing and Validation

### 5.1 Update Test Suite

- Remove tests for removed components
- Simplify integration tests
- Ensure all retained features are tested

### 5.2 Docker Validation

- Verify Docker build and run work with simplified code
- Update Docker configuration if needed

### 5.3 Functional Testing

- Test device flow onboarding
- Test token persistence across restarts
- Test multi-user operation
- Test EventSub connectivity and color changes

## Phase 6: Documentation Update

### 6.1 Update README

- Remove IRC references
- Simplify setup instructions
- Update architecture description

### 6.2 Update Configuration Documentation

- Remove IRC-specific config options
- Simplify configuration examples

## Implementation Order

1. Phase 1 (IRC Removal) - High priority, enables EventSub-only operation
2. Phase 2 (Logging) - Medium priority, improves maintainability
3. Phase 3 (Overengineering) - High priority, reduces complexity
4. Phase 4 (Cleanup) - Low priority, polish
5. Phase 5 (Testing) - Critical, ensures functionality
6. Phase 6 (Documentation) - Low priority, user-facing

## Risk Assessment

- **Zero Risk**: Removing IRC since EventSub is already the main operation mode and IRC was legacy
- **Medium Risk**: Simplifying rate limiting may cause API limit issues
- **Low Risk**: Logging and health monitoring changes are mostly cosmetic

## Success Criteria

- Application builds and runs in Docker
- Device flow onboarding works
- Tokens persist across restarts
- Multi-user support functional
- EventSub chat backend operational
- Color changes work reliably
- Codebase reduced by ~40-50% lines
- No complex abstractions remaining
- Standard Python logging used throughout
