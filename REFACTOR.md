# Refactoring Plan for Single Responsibility Principle Compliance

## Introduction/Overview

This refactoring plan addresses critical violations of the Single Responsibility Principle (SRP) in the Twitch Color Changer codebase. Analysis has identified four files exceeding 500 lines that handle multiple, unrelated responsibilities, compromising maintainability, testability, and long-term reliability for unattended operation.

### Problematic Files Identified

1. **`src/chat/eventsub_backend.py`** (763 lines): Acts as an orchestrator but directly implements connection management, subscription handling, message processing, reconnection logic, and token management.

2. **`src/auth_token/manager.py`** (1062 lines): Manages token lifecycle but also handles background task coordination, hook management, client caching, and validation logic.

3. **`src/config/core.py`** (512 lines): Handles configuration persistence but also performs validation, normalization, and token provisioning.

4. **`src/chat/websocket_connection_manager.py`** (518 lines): Manages WebSocket connections but also implements reconnection strategies, state tracking, and message transmission.

### Refactoring Goals

- Ensure all files remain under 500 lines
- Strictly adhere to SRP with one responsibility per class/module
- Preserve core functionality without alterations
- Balance high maintainability and testability without over-engineering
- Prioritize reliability and resilience for long-running operation
- Maintain pure code without bloat or shims

## Detailed Refactoring Steps

### 1. Refactoring `src/chat/eventsub_backend.py`

**Current Issues**: The class orchestrates components but implements multiple concerns directly, including connection setup, subscription management, message handling, and reconnection.

**Proposed New Classes/Modules**:

- **`ConnectionCoordinator`**: Responsible for initializing and coordinating all component dependencies (WebSocket manager, subscription manager, message processor, channel resolver, token manager, cache manager).

- **`SubscriptionCoordinator`**: Handles subscription lifecycle including primary channel subscription, resubscription after reconnection, and channel joining/leaving.

- **`MessageCoordinator`**: Manages message processing flow including handling WebSocket messages, session reconnects, and idle optimization.

- **`ReconnectionCoordinator`**: Coordinates reconnection logic including session reconnect handling, resubscription, and connection health validation.

**Extraction Methods**:

- Move `_initialize_components()` to `ConnectionCoordinator.__init__()`
- Move `_subscribe_primary_channel()`, `_resubscribe_all_channels()`, `_join_additional_channels()` to `SubscriptionCoordinator`
- Move `_handle_message()`, `listen()` to `MessageCoordinator`
- Move `_handle_reconnect()`, `_validate_connection_health()`, `_handle_session_reconnect()` to `ReconnectionCoordinator`

**Integration Points**:

- `EventSubChatBackend` retains orchestration role, delegating to coordinators via composition.
- Coordinators communicate through the backend's existing component references.
- Maintain backward compatibility by keeping public API unchanged.

### 2. Refactoring `src/auth_token/manager.py`

**Current Issues**: The singleton manager handles token operations but also manages background tasks, hooks, client caching, and validation, creating tight coupling.

**Proposed New Classes/Modules**:

- **`TokenValidator`**: Dedicated to token validation logic including remote validation and scope checking.

- **`TokenRefresher`**: Handles token refresh operations including lock management, client retrieval, and refresh outcome application.

- **`BackgroundTaskManager`**: Manages the background refresh loop, drift correction, and periodic validation.

- **`HookManager`**: Handles registration and firing of update and invalidation hooks.

- **`ClientCache`**: Manages TokenClient caching and retrieval.

**Extraction Methods**:

- Move `validate()`, `_remaining_seconds()`, `_assess_token_health()` to `TokenValidator`
- Move `ensure_fresh()`, `_refresh_with_lock()`, `_apply_successful_refresh()` to `TokenRefresher`
- Move `_background_refresh_loop()`, `_process_single_background()`, `_maybe_periodic_or_unknown_resolution()` to `BackgroundTaskManager`
- Move `register_update_hook()`, `register_invalidation_hook()`, `_maybe_fire_update_hook()`, `_maybe_fire_invalidation_hook()` to `HookManager`
- Move `_get_client()` and client cache attributes to `ClientCache`

**Integration Points**:

- `TokenManager` becomes a facade, composing the new classes.
- Maintain singleton pattern through delegation.
- Background task management integrates with existing asyncio task handling.

### 3. Refactoring `src/config/core.py`

**Current Issues**: Configuration management is mixed with validation, normalization, and token provisioning responsibilities.

**Proposed New Classes/Modules**:

- **`ConfigLoader`**: Handles loading user configurations from files and raw data processing.

- **`ConfigSaver`**: Manages saving configurations to files with checksum verification.

- **`ConfigValidator`**: Performs validation and filtering of user configurations.

- **`TokenSetupCoordinator`**: Coordinates token provisioning and scope validation (integrates existing `TokenProvisioner`).

**Extraction Methods**:

- Move `load_users_from_config()`, `get_configuration()` to `ConfigLoader`
- Move `save_users_to_config()`, `update_user_in_config()` to `ConfigSaver`
- Move `_validate_and_filter_users()`, `_validate_and_filter_users_to_dataclasses()` to `ConfigValidator`
- Move `setup_missing_tokens()`, token validation logic to `TokenSetupCoordinator`

**Integration Points**:

- Core functions become thin wrappers delegating to specialized classes.
- Maintain existing function signatures for backward compatibility.
- Token provisioning integrates with existing `TokenProvisioner` without duplication.

### 4. Refactoring `src/chat/websocket_connection_manager.py`

**Current Issues**: WebSocket management includes connection lifecycle, reconnection logic, and message handling in a single class.

**Proposed New Classes/Modules**:

- **`WebSocketConnector`**: Handles basic WebSocket connection establishment and cleanup.

- **`ReconnectionManager`**: Manages reconnection attempts with exponential backoff and circuit breaker integration.

- **`MessageTransceiver`**: Handles sending and receiving WebSocket messages with timeout management.

- **`ConnectionStateManager`**: Tracks connection state, activity monitoring, and health checks.

**Extraction Methods**:

- Move `connect()`, `_cleanup_connection()`, `disconnect()` to `WebSocketConnector`
- Move `reconnect()`, `_reconnect_with_backoff()`, `_handle_challenge()` to `ReconnectionManager`
- Move `send_json()`, `receive_message()` to `MessageTransceiver`
- Move state attributes and `is_healthy()`, `is_connected` to `ConnectionStateManager`

**Integration Points**:

- `WebSocketConnectionManager` orchestrates the new components.
- Circuit breaker and activity tracking integrate through composition.
- Maintain existing public API for compatibility.

## Phased Implementation Approach

### Phase 0: delete all tests

- Delete all tests
- Remove test related instructions from AGENTS.md

### Phase 1: EventSub Backend Refactoring

**Dependencies**: None
**Scope**: Extract coordinators from `src/chat/eventsub_backend.py`
**Estimated Impact**: High (core chat functionality)

### Phase 1: Cross-examination and fixes

Delegate an agent to do a thorough cross-examination then fix all issues
Repeat until you get a totally successful cross-examination

### Phase 1: User validation and fixes

Ask the user to test the application. If the user finds bugs, fix them then ask him again. Repeat until no bugs found by the user then move to Phase 2

### Phase 2: Token Manager Refactoring

**Dependencies**: Phase 1 completion
**Scope**: Extract specialized classes from `src/auth_token/manager.py`
**Estimated Impact**: High (authentication system)

### Phase 2: Cross-examination and fixes

Delegate an agent to do a thorough cross-examination then fix all issues
Repeat until you get a totally successful cross-examination

### Phase 2: User validation and fixes

Ask the user to test the application. If the user finds bugs, fix them then ask him again. Repeat until no bugs found by the user then move to Phase 3

### Phase 3: Configuration Core Refactoring

**Dependencies**: Phase 2 completion
**Scope**: Extract configuration management classes from `src/config/core.py`
**Estimated Impact**: Medium (configuration system)

### Phase 3: Cross-examination and fixes

Delegate an agent to do a thorough cross-examination then fix all issues
Repeat until you get a totally successful cross-examination

### Phase 3: User validation and fixes

Ask the user to test the application. If the user finds bugs, fix them then ask him again. Repeat until no bugs found by the user then move to Phase 4

### Phase 4: WebSocket Manager Refactoring

**Dependencies**: Phase 3 completion
**Scope**: Extract connection management classes from `src/chat/websocket_connection_manager.py`
**Estimated Impact**: Medium (WebSocket connectivity)

### Phase 4: Cross-examination and fixes

Delegate an agent to do a thorough cross-examination then fix all issues
Repeat until you get a totally successful cross-examination

### Phase 4: User validation and fixes

Ask the user to test the application. If the user finds bugs, fix them then ask him again. Repeat until no bugs found by the user then move to phase 5

### Phase 5: Testing

#### IMPORTANT MANDATORY REQUIREMENTS

- **Always** run test with 10 seconds timeout
- The whole test suite must pass in **60 seconds or less**
- 0 failed tests
- 0 Pytest warnings

#### Phase tasks

- Build a compprehensive, solid and efficient testing infrastructure
  - Fixtures
  - Templates
  - Comprehensive Test-writing instructions in a md file in /tests
  - Comprehendive agent instructions in ai-rules.md
- Write unit tests to reach 95% coverage
- Delegate a cross-examination to check the quality and coverage and 100% passing tests (without pytest warnings)
- Fix issues then repeat cross-examination/fixes until 95% coverage, all tests passing with no pytest warnings
- Write integration tests
- Delegate a cross-examination to check the quality and 100% passing tests (without pytest warnings)
- Fix issues then repeat cross-examination/fixes until all tests passing with no pytest warnings
- Write e2e tests
- Delegate a cross-examination to check the quality and 100% passing tests (without pytest warnings)
- Fix issues then repeat cross-examination/fixes until all tests passing with no pytest warnings

## Conclusion

This refactoring will yield significant benefits in maintainability through focused responsibilities, improved testability via smaller units, and enhanced reliability for long-running operation through better separation of concerns. The phased approach minimizes risk while ensuring each phase delivers immediate SRP compliance improvements. Expected outcomes include reduced bug surface area, easier debugging, and sustainable codebase evolution without compromising the application's core functionality or performance requirements.
