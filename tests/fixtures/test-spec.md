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

See the [prior RFC](https://example.com/rfc/auth-v2) for historical context and the `__deprecated__` flag in `auth/legacy.py`.

## Architecture

### Token Flow

```
Client                    API Gateway                Auth Service
  |                           |                          |
  |-- POST /auth/login ------>|                          |
  |                           |-- validate credentials ->|
  |                           |<-- JWT + refresh token --|
  |<-- Set-Cookie: jwt -------|                          |
  |                           |                          |
  |-- GET /api/data --------->|                          |
  |                           |-- verify JWT (local) --->|
  |<-- 200 OK + data ---------|                          |
```

### Database Schema

| Table | Columns | Index | Notes |
| --- | --- | --- | --- |
| `users` | id, email, name, created_at | email (unique) | Primary user record |
| `credentials` | id, user_id, type, hash | user_id + type | Supports password, passkey, oauth |
| `refresh_tokens` | id, user_id, token_hash, expires_at | token_hash, user_id | Rotated on each use |
| `oauth_providers` | id, name, client_id, client_secret | name (unique) | Google, GitHub, etc. |
| `sessions` | id, user_id, ip, user_agent, last_seen | user_id, last_seen | For audit trail only |

### Rate Limiting

| Endpoint | Limit | Window | Action on exceed |
| --- | --- | --- | --- |
| `/auth/login` | 5 attempts | 15 min | Lock account + notify |
| `/auth/refresh` | 30 requests | 1 min | Return 429 |
| `/auth/register` | 3 accounts | 1 hour | Block IP |
| `/auth/forgot` | 2 emails | 30 min | Silent drop |

## Implementation Plan

### Phase 1: Core JWT Infrastructure

1. Add `jose` dependency for JWT signing/verification
2. Implement `TokenService` with `sign()`, `verify()`, `refresh()` methods
3. Create middleware that extracts JWT from `Authorization` header or cookie
4. Add `/auth/login` endpoint returning JWT + refresh token
5. Add `/auth/refresh` endpoint with token rotation

Key code changes:

```python
class TokenService:
    def __init__(self, secret: str, algorithm: str = "HS256"):
        self.secret = secret
        self.algorithm = algorithm

    def sign(self, payload: dict, expires_in: int = 3600) -> str:
        payload["exp"] = time.time() + expires_in
        payload["iat"] = time.time()
        return jwt.encode(payload, self.secret, algorithm=self.algorithm)

    def verify(self, token: str) -> dict:
        return jwt.decode(token, self.secret, algorithms=[self.algorithm])
```

### Phase 2: OAuth Integration

Add support for external identity providers:

- **Google** — OpenID Connect, email scope
- **GitHub** — OAuth 2.0, `user:email` scope
- **Microsoft** — Azure AD, enterprise SSO

```json
{
  "providers": {
    "google": {
      "client_id": "xxx.apps.googleusercontent.com",
      "scopes": ["openid", "email", "profile"]
    },
    "github": {
      "client_id": "Iv1.xxxxxxxxxxxx",
      "scopes": ["user:email"]
    }
  }
}
```

### Phase 3: Passkey Support

WebAuthn/FIDO2 integration for passwordless login:

1. Registration: generate challenge, store credential public key
2. Authentication: verify assertion against stored public key
3. Fallback: allow password login if passkey fails

> This requires a **secure context** (HTTPS) and a compatible browser. Safari on iOS 16+, Chrome 108+, Firefox 120+.

## API Reference

### POST /auth/login

Request:
```json
{
  "email": "user@example.com",
  "password": "s3cret"
}
```

Response (200):
```json
{
  "access_token": "eyJhbG...",
  "refresh_token": "dGhpcyBpcyBh...",
  "expires_in": 3600,
  "token_type": "Bearer"
}
```

### POST /auth/refresh

Request:
```json
{
  "refresh_token": "dGhpcyBpcyBh..."
}
```

Response (200): same as login

### DELETE /auth/logout

Invalidates the current refresh token. Access tokens remain valid until expiry (stateless).

---

## Migration Plan

| Step | Action | Rollback |
| --- | --- | --- |
| 1 | Deploy auth service with dual-mode (cookie + JWT) | Revert deploy |
| 2 | Migrate mobile apps to JWT (1 week soak) | Feature flag off |
| 3 | Migrate web frontend to JWT | Feature flag off |
| 4 | Remove cookie support from auth service | Re-enable cookie middleware |
| 5 | Drop `session_store` table | *Not reversible* |

## Security Considerations

- JWT secret must be **at least 256 bits** — use `openssl rand -hex 32`
- Refresh tokens must be **single-use** with rotation
- All tokens must have `aud` (audience) and `iss` (issuer) claims
- Failed login attempts must be rate-limited (see table above)
- The `/auth/forgot` endpoint must ***not*** reveal whether an email exists

## Open Questions

1. Should we support **silent refresh** via hidden iframe, or require explicit refresh calls?
2. What's the right access token TTL? 15 minutes (secure) vs 1 hour (convenient)?
3. Do we need a `/auth/introspect` endpoint for service-to-service auth?

---

*Last updated: 2026-03-17*
