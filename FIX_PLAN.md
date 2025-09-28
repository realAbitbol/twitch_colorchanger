# Fix Plan for Audit Issues

This document provides detailed step-by-step instructions for coding agents to fix each issue identified in the technical audit.

## Critical Issues

### 1. TokenValidator Double Lock Deadlock (`src/auth_token/token_validator.py:39-57`)

**Problem**: Double acquisition of `_tokens_lock` causes deadlock in validation operations.

**Fix Steps**:
1. Read the current `validate()` method in `src/auth_token/token_validator.py` to understand the lock usage pattern.
2. Identify the two lock acquisitions: first at line 39 for `self.manager._tokens_lock`, second at line 52 for the same lock.
3. Restructure the method to acquire the lock once at the beginning and hold it throughout the validation process.
4. Move all operations that require the lock inside the single lock context.
5. Ensure that async operations within the lock are minimal to avoid blocking other operations.
6. Test the fix by running existing unit tests for `TokenValidator`.
7. Run `make lint` to ensure no linting errors.
8. Verify with concurrent validation tests to ensure no deadlock occurs.

### 2. Async Persistence Global State Race (`src/config/async_persistence.py:34-37`)

**Problem**: Concurrent updates to global `_PENDING` dict without synchronization.

**Fix Steps**:
1. Examine the `queue_user_update()` function in `src/config/async_persistence.py`.
2. Identify all access points to the global `_PENDING` dictionary and `_FLUSH_TASK`.
3. Add a module-level asyncio.Lock to protect access to these global variables.
4. Modify `queue_user_update()` to acquire the lock before accessing or modifying `_PENDING`.
5. Ensure the lock is released properly in all code paths, including exceptions.
6. Test with concurrent user update operations to verify thread-safety.
7. Run unit tests for async persistence functionality.
8. Execute `make lint` and ensure no new warnings.

### 3. TokenManager Concurrency Race (`src/auth_token/manager.py:341-342`)

**Problem**: Multiple bots accessing shared TokenManager during refresh operations.

**Fix Steps**:
1. Analyze the TokenManager class in `src/auth_token/manager.py` to understand shared state access.
2. Identify methods that modify shared token state (likely `refresh_tokens_for_user` or similar).
3. Add proper locking around shared state modifications using existing `_tokens_lock`.
4. Ensure that read operations that depend on consistency also acquire the lock.
5. For cross-bot operations, consider using a higher-level coordination mechanism if needed.
6. Test with multiple bot instances accessing the same TokenManager concurrently.
7. Verify that token refreshes are atomic and don't interfere with each other.
8. Run `make test` to ensure no regressions.

### 4. Config Persistence Deadlock (`src/config/async_persistence.py:199-205`)

**Problem**: Circular lock dependencies between TokenManager and config persistence.

**Fix Steps**:
1. Map out the lock acquisition order in both `async_persistence.py` and `token_validator.py`.
2. Identify where TokenManager locks are acquired before config persistence locks.
3. Establish a consistent lock ordering hierarchy (e.g., always acquire TokenManager locks before config locks).
4. Modify the code to follow this hierarchy, potentially restructuring method calls.
5. Use timeout locks where possible to detect deadlocks during development.
6. Test with operations that trigger both token validation and config persistence.
7. Implement deadlock detection in tests to catch future violations.
8. Ensure `make test` passes with the changes.

### 5. Color Rejection Strikes Race (`src/color/service.py:221-222`)

**Problem**: Unsynchronized access to bot instance attributes during concurrent color changes.

**Fix Steps**:
1. Locate the `_handle_hex_rejection` method in `src/color/service.py`.
2. Identify where `getattr/setattr` is used on `self.bot._hex_rejection_strikes`.
3. Add a lock to the bot instance or color service to protect this attribute.
4. Modify all access to `_hex_rejection_strikes` to be within the lock context.
5. Ensure atomic increment/decrement operations.
6. Test with concurrent color change requests that trigger rejections.
7. Verify that strike counting is accurate under load.
8. Run `make lint` and ensure code quality standards.

### 6. Stale Connection Detection Failure (`src/chat/connection_state_manager.py:58-86`)

**Problem**: `is_healthy()` always returns True, masking unhealthy connections.

**Fix Steps**:
1. Examine the `is_healthy()` method in `src/chat/connection_state_manager.py`.
2. Identify the logic that should check for stale connections (>60s inactivity).
3. Implement proper health checking based on last activity timestamp.
4. Add logging for health check results.
5. Test with connections that have been idle for various periods.
6. Ensure health checks don't interfere with active connections.
7. Update any dependent code that assumes `is_healthy()` always returns True.
8. Verify with integration tests.

### 7. Incomplete Channel Leaving (`src/chat/eventsub_backend.py:358-378`)

**Problem**: Channel removal without EventSub unsubscription, causing resource leaks.

**Fix Steps**:
1. Analyze the `leave_channel()` method in `src/chat/eventsub_backend.py`.
2. Identify where channels are removed from internal lists.
3. Add EventSub unsubscription calls before removing channels.
4. Handle unsubscription failures gracefully without failing the leave operation.
5. Ensure proper cleanup of all EventSub resources associated with the channel.
6. Test channel leaving with active EventSub subscriptions.
7. Verify that API quota is not consumed by zombie subscriptions.
8. Run comprehensive tests for channel lifecycle management.

### 8. Message Loss in Health Validation (`src/chat/reconnection_coordinator.py:118-143`)

**Problem**: Real messages consumed during connection health checks.

**Fix Steps**:
1. Examine the `validate_connection_health()` method in `src/chat/reconnection_coordinator.py`.
2. Identify where WebSocket messages are received and discarded.
3. Modify the health check to not consume real messages, or process them appropriately.
4. Use a separate health check mechanism that doesn't interfere with message flow.
5. Ensure health validation doesn't drop legitimate chat messages.
6. Test with active message streams during reconnection scenarios.
7. Verify message integrity during health checks.
8. Update tests to cover this scenario.

### 9. Infinite Reconnection Loop Risk (`src/bot/connection_manager.py:263-311`)

**Problem**: Potential indefinite reconnection attempts under persistent failures.

**Fix Steps**:
1. Analyze the `_attempt_reconnect` method in `src/bot/connection_manager.py`.
2. Add time-based limits to prevent infinite loops (e.g., maximum total reconnection time).
3. Implement exponential backoff with a maximum delay (60s as noted).
4. Add failure pattern detection to escalate after consecutive failures.
5. Ensure proper loop termination conditions.
6. Test with persistent connection failures.
7. Verify graceful degradation after max attempts.
8. Run long-running tests to ensure stability.

### 10. Memory Leak in Color Cache (`src/bot/color_changer.py:112-117`)

**Problem**: Unbounded cache growth without cleanup mechanism.

**Fix Steps**:
1. Examine the `_current_color_cache` in `src/color_changer.py`.
2. Implement cache size limits and TTL-based cleanup.
3. Add periodic cleanup routine or lazy cleanup on access.
4. Ensure thread-safe cache operations.
5. Test with long-running color change sequences.
6. Monitor memory usage during extended operation.
7. Verify cache hit rates and performance impact.
8. Run memory profiling tests.

### 11. Incomplete Batch Persistence Recovery (`src/config/async_persistence.py:152-173`)

**Problem**: Partial batch failures without rollback or compensation.

**Fix Steps**:
1. Analyze the batch persistence logic in `async_persistence.py`.
2. Implement atomic batch operations with rollback on partial failures.
3. Add compensation logic for failed operations.
4. Ensure transactional consistency across user updates.
5. Test with partial failure scenarios.
6. Verify data integrity after failures.
7. Implement proper error reporting for batch operations.
8. Run comprehensive persistence tests.

### 12. Unhandled Hook Exceptions (`src/color/service.py:228-232`)

**Problem**: Hook failures can crash color change operations.

**Fix Steps**:
1. Locate hook invocation in `_handle_hex_rejection` method.
2. Wrap hook calls in try-except blocks.
3. Log hook failures without failing the main operation.
4. Consider making hooks optional or with timeouts.
5. Test with failing hook implementations.
6. Ensure color change operations continue despite hook failures.
7. Add monitoring for hook failure rates.
8. Update error handling patterns.

## High Issues

### 13. Circuit Breaker Lock Contention (`src/utils/circuit_breaker.py:85-117`)

**Problem**: Locks held during entire operation block concurrent calls.

**Fix Steps**:
1. Examine the `call` method in `circuit_breaker.py`.
2. Restructure to release lock after state checks and reacquire only for updates.
3. Minimize lock hold time for long-running operations.
4. Test with concurrent circuit breaker calls.
5. Verify performance improvement under load.
6. Ensure state consistency is maintained.
7. Run stress tests for circuit breaker concurrency.

### 14. Global Circuit Breaker Registry Leak (`src/utils/circuit_breaker.py:166-234`)

**Problem**: Instances accumulate indefinitely without cleanup.

**Fix Steps**:
1. Analyze the global `_circuit_breakers` registry.
2. Implement cleanup mechanism based on inactivity or explicit removal.
3. Add registry size limits and LRU eviction.
4. Ensure thread-safe registry operations.
5. Test with long-running applications creating many circuit breakers.
6. Monitor registry growth and cleanup effectiveness.
7. Implement proper lifecycle management.
8. Run memory leak tests.

### 15. Memory Leak in User Lock Registry (`src/config/async_persistence.py:42-44`)

**Problem**: User locks retained beyond TTL without pruning.

**Fix Steps**:
1. Examine the `_USER_LOCKS` registry in `async_persistence.py`.
2. Implement TTL-based pruning in the `_prune_user_locks` function.
3. Add periodic cleanup or trigger cleanup on registry access.
4. Ensure locks are properly cleaned up when users are removed.
5. Test with many user operations over time.
6. Verify lock registry doesn't grow unbounded.
7. Monitor lock contention and cleanup frequency.
8. Run extended operation tests.

### 16. Background Task Interference (`src/auth_token/background_task_manager.py:127-132`)

**Problem**: Refresh loops not coordinated with bot lifecycle.

**Fix Steps**:
1. Analyze background task management in `background_task_manager.py`.
2. Add proper coordination with bot shutdown signals.
3. Implement graceful task cancellation on bot stop.
4. Ensure background tasks don't prevent clean shutdown.
5. Test bot lifecycle with active background operations.
6. Verify no orphaned tasks after shutdown.
7. Add task monitoring and health checks.
8. Run integration tests for bot lifecycle.

### 17. Cache Inconsistency (`src/chat/cache_manager.py:213-218`)

**Problem**: Channel cache updates lack transactional guarantees.

**Fix Steps**:
1. Examine cache update operations in `cache_manager.py`.
2. Implement atomic cache updates with rollback on failure.
3. Add cache consistency checks and repair mechanisms.
4. Ensure cache state matches actual system state.
5. Test with concurrent cache operations.
6. Verify cache integrity after failures.
7. Implement cache validation routines.
8. Run cache consistency tests.

### 18. State Synchronization Issues (`src/auth_token/hook_manager.py:77-78`)

**Problem**: Hook execution order not guaranteed during concurrent operations.

**Fix Steps**:
1. Analyze hook execution in `hook_manager.py`.
2. Implement ordered hook execution or make order explicit.
3. Add synchronization for hook state changes.
4. Ensure hooks see consistent state snapshots.
5. Test with concurrent hook triggering.
6. Verify hook execution order and state consistency.
7. Add hook execution monitoring.
8. Run concurrent operation tests.

### 19. Broad Exception Masking (Multiple locations)

**Problem**: Overly broad exception handling hides programming errors.

**Fix Steps**:
1. Identify locations with broad `except Exception` or similar.
2. Replace with specific exception types where possible.
3. Add logging for unexpected exceptions.
4. Ensure programming errors surface appropriately.
5. Test with various failure scenarios.
6. Verify error visibility and debugging capability.
7. Update error handling patterns across the codebase.
8. Run comprehensive error handling tests.

### 20. Retry Logic Returns None (`src/utils/retry.py:62-65`)

**Problem**: Failed retries return None instead of raising exceptions.

**Fix Steps**:
1. Examine the retry logic in `retry.py`.
2. Modify to raise a specific exception (e.g., `RetryExhaustedError`) on exhaustion.
3. Include attempt details in the exception.
4. Update callers to handle the new exception type.
5. Test retry exhaustion scenarios.
6. Verify error propagation works correctly.
7. Update documentation and tests.
8. Run retry logic tests.

### 21. Insufficient Device Flow Recovery (`src/bot/token_handler.py:256-320`)

**Problem**: Single auth failure blocks all subsequent attempts.

**Fix Steps**:
1. Analyze device flow handling in `token_handler.py`.
2. Add retry logic for device authorization failures.
3. Implement backoff for repeated failures.
4. Allow manual intervention triggers.
5. Test with device flow failures.
6. Verify recovery from auth failures.
7. Add monitoring for auth failure rates.
8. Run device flow integration tests.

## Medium & Low Issues

### 22. Sequential API Processing (`src/api/twitch.py:202-221`)

**Problem**: User lookups processed sequentially instead of concurrently.

**Fix Steps**:
1. Examine `get_users_by_login` in `twitch.py`.
2. Replace sequential processing with `asyncio.gather` for concurrency.
3. Add rate limiting to respect API limits.
4. Test with large user lists.
5. Verify performance improvement.
6. Ensure API quota compliance.
7. Run API performance tests.

### 23. File Handle Leaks (`src/config/repository.py:169-203`)

**Problem**: Incomplete cleanup in atomic write operations.

**Fix Steps**:
1. Analyze atomic write operations in `repository.py`.
2. Ensure all file handles are properly closed in all code paths.
3. Add context managers for file operations.
4. Test with interrupted write operations.
5. Verify no file handle leaks.
6. Run file I/O stress tests.
7. Monitor file descriptor usage.

### 24. Weak Validation Logic (`src/color/service.py:200-201`)

**Problem**: Dead code in status mapping.

**Fix Steps**:
1. Examine the validation logic in `service.py`.
2. Remove unreachable code or clarify the logic.
3. Ensure all code paths are meaningful.
4. Test color change validation thoroughly.
5. Verify no dead code remains.
6. Update tests to cover all paths.
7. Run validation tests.

### 25. Inconsistent Error Data Handling (`src/errors/handling.py:298-303`)

**Problem**: Silent failures in user lookup operations.

**Fix Steps**:
1. Analyze error handling in `handling.py`.
2. Add proper error logging and data preservation.
3. Ensure consistent error reporting.
4. Test with various error conditions.
5. Verify error visibility.
6. Update error handling patterns.
7. Run error handling tests.

### 26. Missing Configuration Timeouts (`src/api/twitch.py:36-47`)

**Problem**: No explicit HTTP session timeouts.

**Fix Steps**:
1. Examine ClientSession creation in `twitch.py`.
2. Add explicit timeout configuration.
3. Test with slow network conditions.
4. Verify timeout behavior.
5. Ensure reasonable defaults.
6. Run network timeout tests.

## Architectural Integration Issues

### 27. State Propagation Delays

**Problem**: Token state changes may not propagate atomically to dependent components.

**Fix Steps**:
1. Analyze token state propagation across modules.
2. Implement atomic state updates with proper synchronization.
3. Add state consistency checks.
4. Ensure all dependent components see consistent state.
5. Test state propagation under load.
6. Verify atomicity of state changes.
7. Run cross-module integration tests.

### 28. Background Task Supervision

**Problem**: Unhandled exceptions in background tasks go undetected.

**Fix Steps**:
1. Implement proper task supervision and monitoring.
2. Add exception handling and reporting for background tasks.
3. Ensure task failures are surfaced appropriately.
4. Test with failing background operations.
5. Verify task health monitoring.
6. Add task lifecycle management.
7. Run background task tests.

### 29. Resource Leak Accumulation

**Problem**: Multiple sources of gradual resource exhaustion.

**Fix Steps**:
1. Audit all resource allocation points.
2. Implement proper cleanup and monitoring.
3. Add resource usage tracking.
4. Test for resource leaks over time.
5. Verify cleanup effectiveness.
6. Run long-running resource monitoring tests.

### 30. Silent Failure Modes

**Problem**: Many error paths log minimally or not at all.

**Fix Steps**:
1. Review error logging across the codebase.
2. Add comprehensive error logging with context.
3. Ensure all failure modes are visible.
4. Test error reporting under various conditions.
5. Verify log completeness.
6. Update logging configuration.
7. Run error logging tests.