# Twitch Color Changer Bot – Functional Documentation

Comprehensive description of runtime behavior, architecture, and operational characteristics (IRC + EventSub backends). Requires **Python 3.13+**.

---

## Table of Contents

- [1. Project Overview](#1-project-overview)
- [2. Core Functionality](#2-core-functionality)
  - [2.1 Primary Features](#21-primary-features)
  - [2.2 Color Change Flow](#22-color-change-flow)
  - [2.3 Runtime Chat Commands](#23-runtime-chat-commands)
- [3. Chat Backend Abstraction](#3-chat-backend-abstraction)
  - [3.1 Implementations](#31-implementations)
  - [3.2 Interface Responsibilities](#32-interface-responsibilities)
  - [3.3 Design Rationale](#33-design-rationale)
- [4. IRC Backend Summary](#4-irc-backend-summary)
- [5. EventSub Backend (Default)](#5-eventsub-backend-default)
  - [5.1 Transport & Session](#51-transport--session)
  - [5.2 Subscriptions](#52-subscriptions)
  - [5.3 Message Handling](#53-message-handling)
  - [5.4 Resilience](#54-resilience)
  - [5.5 Broadcaster ID Cache](#55-broadcaster-id-cache)
  - [5.6 Limitations](#56-limitations)
- [6. Token Lifecycle Management](#6-token-lifecycle-management)
  - [Device Flow Sequence](#device-flow-sequence)
- [7. Configuration System](#7-configuration-system)
- [8. Multi-Bot Orchestration](#8-multi-bot-orchestration)
- [9. Logging & Observability](#9-logging--observability)
  - [9.1 Event Template Catalog (Recent Notables)](#91-event-template-catalog-recent-notables)
  - [9.2 Security & Resilience Updates](#92-security--resilience-updates)
- [10. Deployment Architecture](#10-deployment-architecture)
- [11. Performance Characteristics](#11-performance-characteristics)
- [12. Dependencies & Tooling](#12-dependencies--tooling)
- [13. Future Enhancements](#13-future-enhancements)

## 1. Project Overview

Automatically changes a user's Twitch chat color after each of their own messages. Supports multiple users, preset & hex colors, robust token lifecycle management, pluggable chat backends (IRC & EventSub), Docker deployment, and live configuration reload.

## 2. Core Functionality

### 2.1 Primary Features

1. Automatic color change after each own message
2. Multi-user concurrent operation (independent bot instances)
3. Preset + random hex colors (Prime/Turbo users get true hex)
4. Smart Turbo/Prime detection with persistent fallback
5. No immediate repeat color (avoids last applied value)
6. Startup current color discovery (first change guaranteed different)
7. Proactive token refresh + validation (pre-expiry)
8. IRC backend with health & reconnection
9. EventSub backend (default) with resilient subscriptions
10. Live configuration reload (watchdog + debounce)
11. Channel deduplication & persistence
12. Structured event logging & event template catalog audit
13. Per-user runtime enable/disable commands (`ccd` / `cce`)
14. Directory-based persistence (config + timestamped backups + broadcaster ID cache)

### 2.2 Color Change Flow

```text
Own message detected
  → Select new color (≠ current)
    → PUT /helix/chat/color
      → Log success/failure
        → Update stats
```

### 2.3 Runtime Chat Commands

| Command | Effect |
|---------|--------|
| `ccd` | Disable automatic color changes for that user (`enabled=false`) |
| `cce` | Enable automatic color changes (`enabled=true`) |

Only the bot user’s own messages are interpreted. State changes persist to config immediately.

## 3. Chat Backend Abstraction

> Note: EventSub is Twitch's modern, extensible delivery mechanism and now the default for the bot. IRC remains functional as a legacy option and may receive fewer future enhancements.

### 3.1 Implementations

| Backend  | Status        | Transport                                      | Required Scopes                                    |
|----------|---------------|------------------------------------------------|----------------------------------------------------|
| IRC      | Stable (Legacy) | Raw IRC TCP                                    | `chat:read` (implicit)                             |
| EventSub | Default       | EventSub WebSocket (`channel.chat.message` v1) | `chat:read`, `user:read:chat`, `user:manage:chat_color` |

Select via `TWITCH_CHAT_BACKEND=eventsub|irc` (defaults to `eventsub`). No automatic fallback to IRC is performed.

### 3.2 Interface Responsibilities

`connect`, `join_channel`, `listen`, `disconnect`, `update_token`, `set_message_handler`, `set_color_change_handler`.

### 3.3 Design Rationale

Both backends emit only *self* messages to maximize signal quality and enforce parity. Unified logging template (`irc.privmsg`) keeps downstream tooling stable.

## 4. IRC Backend Summary

Standard Twitch IRC client: authentication, capabilities (membership/tags/commands), JOIN confirmation (366), 30s join timeout + retry, stale detection (activity timeout + server ping expectations), forced reconnect logic, and per-channel state tracking.

## 5. EventSub Backend (Default)

### 5.1 Transport & Session

- WebSocket URL: `wss://eventsub.wss.twitch.tv/ws`
- Welcome frame yields `session.id`
- Heartbeat handled by library (30s) – stale if ~70s silence
- One WebSocket per configured bot user

### 5.2 Subscriptions

- Event Type: `channel.chat.message` (v1)
- Condition: `{ broadcaster_user_id, user_id }` restricts delivery to bot user inside each target channel
- Expected set = all configured channels for the bot user
- Missing scopes → `eventsub_missing_scopes` and early token invalidation path

### 5.3 Message Handling

- Filter: process only if `chatter_user_name` == bot username (case-insensitive)
- Normalize to IRC-equivalent log event (`irc.privmsg`) with `backend=eventsub`
- Extract `message.text` and broadcaster context for color trigger pipeline

### 5.4 Resilience

| Mechanism            | Details |
|----------------------|---------|
| Stale Detection      | ~70s inactivity → forced reconnect |
| Reconnect Backoff    | Exponential (1s → 2s → 4s ... cap 60s) + secrets-based jitter |
| Fast Audit           | 60–120s after reconnect verifies all subscriptions |
| Normal Audit         | Every 600s + 0–120s jitter, reconciles missing subscriptions |
| Resubscribe          | Missing channels resubscribed (`eventsub_resubscribe_missing`) |
| Early Invalid Token  | Two 401 subscribe attempts OR 401 on list → `eventsub_token_invalid` |
| Missing Scopes       | 403 subscribe + set diff → `eventsub_missing_scopes` |

### 5.5 Broadcaster ID Cache

File: `broadcaster_ids.cache.json` in config directory (override via `TWITCH_BROADCASTER_CACHE`).

- Reduces repeated Helix lookups for user → ID resolution
- Updated on successful new channel resolution
- Persisted & loaded at startup; gracefully skip corrupt file

### 5.6 Limitations

- Only self messages (design choice for parity & performance)
- Legacy option: you can explicitly select IRC if preferred
- One WebSocket per user (not multiplexed across users—simplifies isolation)

## 6. Token Lifecycle Management

- Device Flow provisioning on demand for missing/invalid tokens
- Startup scope validation (fast detection of revoked scope sets)
- Proactive refresh (<1h remaining) every 10m cycle
  - Validation path now applies the same safety buffer as refresh (avoids late boundary cases)
- Forced refresh at startup ensures fresh window
- Refresh failure → validation fallback → device flow fallback
- Invalidation events (`eventsub_token_invalid`, also generic token invalid logs) annotated with source (refresh, validation, EventSub 401, etc.)
- Scope diff detection triggers early invalidation (prevents wasted retries)
- Expired or expiry-unknown tokens are now proactively force-refreshed in the background loop (no initial 401 needed)
  - Background loop detects drift (event loop stalls) and temporarily doubles refresh headroom to avoid expiry during pauses

### Device Flow Sequence

```text
Startup → Existing tokens checked
  ├─ Valid → continue
  ├─ Refresh fails / invalid → Device flow start
       → Display user_code + verification_uri
       → Poll until approved or times out
       → Store access & refresh tokens → proceed
```

## 7. Configuration System

- Multi-user JSON file (array under `users`)
- Live reload (watchdog) with debounce & self-change suppression
- Timestamped backup files on changes
- Automatic legacy single-user → multi-user conversion
- Channel deduplication + persistence
- `enabled` flag defaults to `true`; runtime toggles persist
- Environment overrides (advanced / container) for file path (`TWITCH_CONF_FILE`) and cache path

## 8. Multi-Bot Orchestration

- Each user = isolated async task (backend, token task, color scheduler)
- Central manager supervises tasks & coordinates graceful shutdown
- Health-check mode (`--health-check`) performs lightweight readiness probe
- Failure isolation: one bot crash does not terminate others (unless systemic)

## 9. Logging & Observability

- Structured events; event name padded to fixed width for column alignment
- Unified message template: `irc.privmsg` across both backends (`backend` tag differentiates)
- Dedicated events for reconnects, audits, scope evaluation, token invalidation sources
- Event template audit script validates all emitted events appear in catalog

### 9.1 Event Template Catalog (Recent Notables)

`eventsub_ws_connected`, `eventsub_subscribed`, `eventsub_resubscribe_missing`, `eventsub_token_scopes`, `eventsub_token_invalid`, `eventsub_missing_scopes`, `eventsub_reconnect_success`, `eventsub_reconnect_failed`, `eventsub_stale_detected`, `auto_color_enabled`, `auto_color_disabled`, `keepalive_color_get_attempt`, `keepalive_color_get_success`, `keepalive_color_get_skip_recent`, `keepalive_color_get_none`.

### 9.2 Security & Resilience Updates

- Secrets-based jitter to reduce correlated reconnects
- Removal of silent `pass` exception blocks—explicit logging instead
- Early invalidation of degraded tokens (reduces wasted subscription churn)
- Scope comparison logging for diagnostic clarity

## 10. Deployment Architecture

- Docker multi-arch images (Alpine base, non-root execution)
- Recommended volume: `./config:/app/config` (config + backups + broadcaster cache)
- Backend selection via environment variable
- Health check route uses lightweight startup argument
- Graceful shutdown on signals; persistent state saved pre-exit

## 11. Performance Characteristics

- Memory: ~30–40 MB per active bot (dominated by Python runtime + aiohttp buffers)
- CPU: Minimal; event-driven I/O dominated
- Scaling: Linear per user (independent connections / WebSocket)
- Latency: Color change typically near real-time; limited by Twitch API & network RTT

## 12. Dependencies & Tooling

- Runtime: `aiohttp`, `httpx`, optional `watchdog`
- Tooling: Ruff (lint/format/imports), mypy (strict), bandit (security), mdformat (optional), pre-commit hooks
- Python: 3.13+ (uses latest stdlib improvements & performance)

## 13. Future Enhancements

- Optional structured/JSON log output mode
- Metrics endpoint (subscription counts, reconnect counters, color success rates)
- Expanded health probes (latency windows, API error budgets)
- EventSub multiplexing optimization (batch subscription refresh)
- Optional metrics emission for keepalive trigger counts & idle distribution

---

This document reflects the current implementation (IRC + EventSub). Experimental features may evolve; refer to commit history for incremental changes.
