# Authentication System Redesign

## Overview

This spec covers the redesign of the authentication system to support **OAuth 2.0**, **SAML**, and **passkey** flows. The goal is to replace the legacy session-cookie system with a modern, stateless JWT architecture.

> **Note:** This is a breaking change. All existing sessions will be invalidated on deploy. Coordinate with the mobile team before merging.

## Motivation

The current auth system has several problems:

- Session cookies are **not portable** across subdomains
- No support for *third-party* identity providers
- Token refresh requires a full page reload
- The `session_store` table has grown to ~~50GB~~ 80GB and is the #1 DB bottleneck

See the [prior RFC](https://example.com/rfc/auth-v2) for historical context.

## Architecture

### Token Flow

```
Client                    API Gateway                Auth Service
  |                           |                          |
  |-- POST /auth/login ------>|                          |
  |                           |-- validate credentials ->|
  |                           |<-- JWT + refresh token --|
  |<-- Set-Cookie: jwt -------|                          |
```

### Rate Limiting

| Endpoint | Limit | Window | Action on exceed |
| --- | --- | --- | --- |
| `/auth/login` | 10 attempts | 15 min | Progressive backoff (1m/5m/15m) |
| `/auth/refresh` | 30 requests | 1 min | Return 429 |
| `/auth/register` | 3 accounts | 1 hour | Block IP |
| `/auth/forgot` | 2 emails | 30 min | Silent drop |

## Implementation Plan

### Phase 1: Core JWT Infrastructure

1. Add `jose` dependency for JWT signing/verification
2. Implement `TokenService` with `sign()`, `verify()`, `refresh()` methods
3. Create middleware that extracts JWT from `Authorization` header or cookie

```python
class TokenService:
    def __init__(self, secret: str, algorithm: str = "HS256"):
        self.secret = secret
        self.algorithm = algorithm

    def sign(self, payload: dict, expires_in: int = 3600) -> str:
        payload["exp"] = time.time() + expires_in
        return jwt.encode(payload, self.secret, algorithm=self.algorithm)
```

### Phase 2: Passkey Support

WebAuthn/FIDO2 integration for passwordless login:

1. Registration: generate challenge, store credential public key
2. Authentication: verify assertion against stored public key
3. Fallback: allow password login if passkey fails
4. Hybrid flow: link passkey + OAuth credentials to single account

> This requires a **secure context** (HTTPS) and a compatible browser. Safari on iOS 16+, Chrome 108+, Firefox 120+.

## Security Considerations

- JWT secret must be **at least 256 bits** — use `openssl rand -hex 32`
- Refresh tokens must be **single-use** with rotation
- All tokens must have `aud` (audience) and `iss` (issuer) claims
- The `/auth/forgot` endpoint must ***not*** reveal whether an email exists

## Open Questions

1. Should we support **silent refresh** via hidden iframe, or require explicit refresh calls?
2. What's the right access token TTL? 15 minutes (secure) vs 1 hour (convenient)?
3. Do we need a `/auth/introspect` endpoint for service-to-service auth?

---

*Last updated: 2026-03-17*
