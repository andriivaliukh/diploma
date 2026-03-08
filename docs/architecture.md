# VPN Backend with 2FA — Architecture Design Document

## Status: Draft
## Last updated: 2026-03-09

---

## 1. Overview

This system is a WireGuard-based VPN backend with built-in two-factor authentication (TOTP). Users authenticate via a REST API (username/password + TOTP), receive time-limited WireGuard credentials, and establish tunnels. A CLI client automates the full flow: login → 2FA → receive config → bring up tunnel.

The core innovation is **session-gated VPN access**: WireGuard peers are only configured on the server after successful 2FA. Sessions expire, and expired peers are automatically removed — enforcing re-authentication.

### Why not just use an external IdP?

Solutions like Firezone and Tailscale delegate 2FA to external identity providers (OIDC/SAML). Our system implements 2FA natively, which:
- Makes the system self-contained (no external dependencies for a diploma demo)
- Gives us full control over the auth flow for the thesis write-up
- Keeps deployment to a single `docker compose up`

### Inspiration from DefGuard

DefGuard uses WireGuard's pre-shared key (PSK) field as a session token — after MFA, the server generates a one-time PSK delivered to both gateway and client. This is elegant but tightly couples session management to WireGuard's PSK mechanism. We take a simpler approach: **the server manages peer lifecycle directly** — adding/removing peers based on session state. This is more transparent and easier to reason about for a thesis.

---

## 2. High-Level Architecture

```
┌─────────────┐       HTTPS (:443)       ┌───────────┐    HTTP (:8000)    ┌──────────────────┐
│  CLI Client  │ ◄──────────────────────► │   Caddy   │ ◄───────────────► │   API Server     │
│  (Docker)    │                          │ (TLS/rev  │   (internal)      │   (FastAPI)      │
└──────┬───────┘                          │  proxy)   │                   └────────┬─────────┘
       │                                  └───────────┘                           │
       │  WireGuard tunnel                                                        │  manages
       │  (UDP :51820)                                                            ▼
       │                                                                 ┌──────────────────┐
       └────────────────────────────────────────────────────────────────►│  WireGuard       │
                                                                         │  Interface       │
                                                                         │  (wg0)           │
                                                                         └──────────────────┘
                                                                                  │
                                                                         ┌────────┴─────────┐
                                                                         │   SQLite DB      │
                                                                         │   (persistent)   │
                                                                         └──────────────────┘
```

### Services / Components

This is a **monolith** — a single FastAPI process that handles everything. This is intentional for a diploma project:
- Simplest possible deployment
- No inter-service communication to debug
- One codebase to present and defend

The monolith contains these internal modules:

| Module | Responsibility |
|--------|---------------|
| `auth` | User registration, login, password hashing, JWT issuance |
| `totp` | TOTP secret management, enrollment, verification |
| `sessions` | VPN session lifecycle (create, validate, expire, revoke) |
| `wireguard` | WireGuard interface management (add/remove peers, generate keys) |
| `api` | FastAPI route definitions, request/response schemas |
| `models` | SQLAlchemy ORM models |
| `config` | Pydantic settings, environment variable loading |
| `tasks` | Background tasks (session expiry cleanup) |

---

## 3. Authentication & Authorization Flow

### 3.1 Registration Flow

```
Client                          API Server
  │                                 │
  │  POST /api/v1/auth/register     │
  │  {username, password}           │
  │ ───────────────────────────────►│
  │                                 │  hash password (argon2)
  │                                 │  create User record
  │                                 │  generate TOTP secret
  │                                 │  store encrypted TOTP secret
  │  {user_id, totp_uri,           │
  │   totp_secret, qr_png_base64}  │
  │ ◄───────────────────────────────│
  │                                 │
  │  POST /api/v1/auth/totp/verify  │
  │  {user_id, totp_code}          │
  │ ───────────────────────────────►│
  │                                 │  verify code matches secret
  │                                 │  mark TOTP as enrolled
  │  {success: true}               │
  │ ◄───────────────────────────────│
```

**Key decisions:**
- TOTP enrollment is **mandatory** — no user can skip 2FA
- The initial TOTP secret is returned at registration; user must verify one code to confirm enrollment
- Until TOTP is verified, the user cannot create VPN sessions

### 3.2 Login Flow (with 2FA)

```
Client                          API Server
  │                                 │
  │  POST /api/v1/auth/login        │
  │  {username, password}           │
  │ ───────────────────────────────►│
  │                                 │  verify password (argon2)
  │  {auth_token (short-lived),    │
  │   requires_totp: true}         │
  │ ◄───────────────────────────────│
  │                                 │
  │  POST /api/v1/auth/totp/verify  │
  │  Authorization: Bearer <auth>   │
  │  {totp_code}                   │
  │ ───────────────────────────────►│
  │                                 │  verify TOTP code
  │                                 │  issue full access JWT
  │  {access_token, expires_in}    │
  │ ◄───────────────────────────────│
```

**Two-step login:**
1. Password verification → returns a short-lived intermediate token (5 min TTL, scope: `totp_verify` only)
2. TOTP verification with intermediate token → returns full-access JWT (configurable TTL, default 24h)

This prevents timing attacks on TOTP by requiring valid password first. The intermediate token is limited in scope — it can only be used for the TOTP verification endpoint.

### 3.3 VPN Session Establishment (Core Flow)

```
Client                          API Server              WireGuard
  │                                 │                       │
  │  POST /api/v1/vpn/sessions      │                       │
  │  Authorization: Bearer <jwt>    │                       │
  │  {device_name,                  │                       │
  │   client_public_key}            │                       │
  │ ───────────────────────────────►│                       │
  │                                 │  validate JWT (full)  │
  │                                 │  validate 2FA done    │
  │                                 │  generate server-side │
  │                                 │   allowed_ips for peer│
  │                                 │  add peer to wg0 ────────────►│
  │                                 │                       │  peer active
  │  {session_id,                   │                       │
  │   server_public_key,            │                       │
  │   server_endpoint,              │                       │
  │   assigned_ip,                  │                       │
  │   dns_servers,                  │                       │
  │   allowed_ips,                  │                       │
  │   expires_at}                   │                       │
  │ ◄───────────────────────────────│                       │
  │                                 │                       │
  │  [client configures wg locally] │                       │
  │  [tunnel established]           │                       │
  │ ════════════════════════════════════════════════════════│
```

**Key design decisions:**

1. **Client generates its own WireGuard keypair** — the private key never leaves the client. Only the public key is sent to the server.

2. **Server adds the peer to WireGuard only after full JWT validation** — this means 2FA is enforced before any tunnel can be established.

3. **Each session = one WireGuard peer entry** — sessions map 1:1 to peers. When a session expires, the peer is removed.

4. **IP allocation**: Server maintains a pool of IPs within the WireGuard subnet (e.g., `10.10.0.0/24`). Each session gets a unique IP. IPs are reclaimed on session expiry.

### 3.4 Session Lifecycle

| State | Description | WireGuard Peer |
|-------|-------------|----------------|
| `active` | Session valid, tunnel operational | Present on wg0 |
| `expired` | TTL exceeded | Removed from wg0 |
| `revoked` | Admin/user forced disconnect | Removed from wg0 |

**Session expiry mechanism:**
- A background task runs every 60 seconds, checking for expired sessions
- Expired sessions: peer removed from WireGuard, session marked `expired` in DB
- The client can also proactively check session validity via `GET /api/v1/vpn/sessions/{id}`
- Sessions have a configurable TTL (default: 8 hours)

**Session revocation:**
- `DELETE /api/v1/vpn/sessions/{id}` — user revokes own session
- Admin endpoint can revoke any session (future: admin role)

---

## 4. API Specification

### 4.1 Auth Endpoints

#### `POST /api/v1/auth/register`
Register a new user with mandatory TOTP enrollment.

**Request:**
```json
{
  "username": "string (3-50 chars, alphanumeric + underscore)",
  "password": "string (min 8 chars)"
}
```

**Response (201):**
```json
{
  "user_id": "uuid",
  "username": "string",
  "totp_uri": "otpauth://totp/VPNService:username?secret=BASE32&issuer=VPNService",
  "totp_secret": "BASE32_SECRET",
  "totp_qr_base64": "base64-encoded PNG"
}
```

**Errors:**
- `409` — username already exists
- `422` — validation error (weak password, invalid username)

#### `POST /api/v1/auth/login`
Authenticate with username/password. Returns intermediate token for TOTP step.

**Request:**
```json
{
  "username": "string",
  "password": "string"
}
```

**Response (200):**
```json
{
  "auth_token": "jwt (scope: totp_verify, TTL: 5min)",
  "requires_totp": true,
  "token_type": "bearer"
}
```

**Errors:**
- `401` — invalid credentials
- `403` — TOTP not yet enrolled (must complete registration)

#### `POST /api/v1/auth/totp/verify`
Verify TOTP code. During registration: confirms enrollment. During login: upgrades to full access token.

**Request:**
```json
{
  "totp_code": "string (6 digits)"
}
```
**Headers:** `Authorization: Bearer <auth_token>`

**Response (200) — login context:**
```json
{
  "access_token": "jwt (scope: full, TTL: 24h)",
  "token_type": "bearer",
  "expires_in": 86400
}
```

**Response (200) — registration context:**
```json
{
  "success": true,
  "message": "TOTP enrollment confirmed"
}
```

**Errors:**
- `401` — invalid or expired auth_token
- `400` — invalid TOTP code

### 4.2 VPN Session Endpoints

#### `POST /api/v1/vpn/sessions`
Create a new VPN session. Requires full-access JWT (2FA completed).

**Request:**
```json
{
  "device_name": "string (1-100 chars)",
  "client_public_key": "string (WireGuard base64 public key)"
}
```
**Headers:** `Authorization: Bearer <access_token>`

**Response (201):**
```json
{
  "session_id": "uuid",
  "server_public_key": "base64",
  "server_endpoint": "host:51820",
  "assigned_ip": "10.10.0.2/32",
  "dns_servers": ["10.10.0.1"],
  "allowed_ips": ["0.0.0.0/0"],
  "expires_at": "2026-03-09T08:00:00Z",
  "keepalive_interval": 25
}
```

**Errors:**
- `401` — invalid/expired token
- `403` — TOTP not verified for this session
- `409` — session limit reached (max active sessions per user exceeded), or duplicate device public key
- `503` — WireGuard interface not available

#### `GET /api/v1/vpn/sessions`
List user's sessions.

**Headers:** `Authorization: Bearer <access_token>`

**Response (200):**
```json
{
  "sessions": [
    {
      "session_id": "uuid",
      "device_name": "string",
      "assigned_ip": "10.10.0.2/32",
      "status": "active|expired|revoked",
      "created_at": "ISO8601",
      "expires_at": "ISO8601",
      "last_handshake": "ISO8601|null"
    }
  ]
}
```

#### `GET /api/v1/vpn/sessions/{session_id}`
Get specific session details.

**Response (200):** Same schema as list item above with additional fields:
```json
{
  "session_id": "uuid",
  "device_name": "string",
  "client_public_key": "base64",
  "assigned_ip": "10.10.0.2/32",
  "status": "active",
  "created_at": "ISO8601",
  "expires_at": "ISO8601",
  "last_handshake": "ISO8601|null",
  "transfer_rx": 0,
  "transfer_tx": 0
}
```

#### `DELETE /api/v1/vpn/sessions/{session_id}`
Revoke a session (removes WireGuard peer).

**Headers:** `Authorization: Bearer <access_token>`

**Response (200):**
```json
{
  "session_id": "uuid",
  "status": "revoked"
}
```

**Errors:**
- `404` — session not found or not owned by user
- `409` — session already expired/revoked

### 4.3 Device Endpoints

#### `GET /api/v1/devices`
List user's registered devices.

**Response (200):**
```json
{
  "devices": [
    {
      "device_id": "uuid",
      "name": "string",
      "public_key": "base64",
      "created_at": "ISO8601",
      "last_active": "ISO8601|null"
    }
  ]
}
```

### 4.4 Health / Info

#### `GET /api/v1/health`
Health check (unauthenticated).

**Response (200):**
```json
{
  "status": "healthy",
  "wireguard": "up|down",
  "version": "0.1.0"
}
```

### 4.5 Admin Endpoints

All admin endpoints require a JWT with `is_admin: true`. Enforced by a `require_admin` FastAPI dependency that checks the JWT payload after standard `get_current_user` authentication.

#### `GET /api/v1/admin/users`
List all registered users.

**Headers:** `Authorization: Bearer <access_token>` (admin only)

**Response (200):**
```json
{
  "users": [
    {
      "user_id": "uuid",
      "username": "string",
      "is_admin": true,
      "is_active": true,
      "totp_enrolled": true,
      "created_at": "ISO8601",
      "active_sessions_count": 2
    }
  ]
}
```

**Errors:**
- `401` — invalid/expired token
- `403` — user is not admin

#### `GET /api/v1/admin/sessions`
List all active VPN sessions across all users.

**Headers:** `Authorization: Bearer <access_token>` (admin only)

**Response (200):**
```json
{
  "sessions": [
    {
      "session_id": "uuid",
      "user_id": "uuid",
      "username": "string",
      "device_name": "string",
      "assigned_ip": "10.10.0.2/32",
      "status": "active",
      "created_at": "ISO8601",
      "expires_at": "ISO8601"
    }
  ]
}
```

#### `DELETE /api/v1/admin/sessions/{session_id}`
Force-revoke any user's VPN session. Removes the WireGuard peer.

**Headers:** `Authorization: Bearer <access_token>` (admin only)

**Response (200):**
```json
{
  "session_id": "uuid",
  "status": "revoked"
}
```

**Errors:**
- `403` — not admin
- `404` — session not found
- `409` — session already expired/revoked

#### `GET /api/v1/admin/settings`
Get current system settings.

**Headers:** `Authorization: Bearer <access_token>` (admin only)

**Response (200):**
```json
{
  "max_sessions_per_user": 1,
  "session_ttl_hours": 8
}
```

#### `PUT /api/v1/admin/settings`
Update system settings.

**Headers:** `Authorization: Bearer <access_token>` (admin only)

**Request:**
```json
{
  "max_sessions_per_user": 3,
  "session_ttl_hours": 12
}
```
All fields optional — only provided fields are updated.

**Response (200):** Same as GET response with updated values.

**Errors:**
- `403` — not admin
- `422` — invalid values (e.g., max_sessions < 1)

---

## 5. WireGuard Integration

### 5.1 Interface Management

The server manages a single WireGuard interface (`wg0`) using **subprocess calls to `wg` and `ip` commands**. We avoid third-party WireGuard libraries to keep the dependency light and use the canonical tooling.

**Operations:**

| Operation | Command |
|-----------|---------|
| Create interface | `ip link add wg0 type wireguard` |
| Set private key | `wg set wg0 private-key /path/to/key` |
| Set listen port | `wg set wg0 listen-port 51820` |
| Add peer | `wg set wg0 peer <pubkey> allowed-ips <ip>/32` |
| Remove peer | `wg set wg0 peer <pubkey> remove` |
| Get peer stats | `wg show wg0 dump` |
| Bring up | `ip link set wg0 up` |
| Assign IP | `ip addr add 10.10.0.1/24 dev wg0` |

### 5.2 WireGuard Module Interface

```python
class WireGuardManager:
    """Manages the WireGuard interface and peer lifecycle."""

    async def initialize(self) -> None:
        """Create and configure wg0 interface if not exists."""

    async def add_peer(
        self,
        public_key: str,
        allowed_ips: str,  # e.g., "10.10.0.2/32"
        preshared_key: str | None = None,
    ) -> None:
        """Add a peer to the WireGuard interface."""

    async def remove_peer(self, public_key: str) -> None:
        """Remove a peer from the WireGuard interface."""

    async def get_peer_stats(self, public_key: str) -> PeerStats | None:
        """Get transfer/handshake stats for a peer."""

    async def list_peers(self) -> list[PeerStats]:
        """List all active peers with stats."""

    def get_server_public_key(self) -> str:
        """Return the server's WireGuard public key."""

    def get_endpoint(self) -> str:
        """Return the server's public endpoint (host:port)."""
```

```python
@dataclass
class PeerStats:
    public_key: str
    allowed_ips: str
    last_handshake: datetime | None
    transfer_rx: int  # bytes
    transfer_tx: int  # bytes
```

### 5.3 IP Address Allocation

- Subnet: `10.10.0.0/24` (configurable)
- `10.10.0.1` — server (wg0 interface)
- `10.10.0.2` through `10.10.0.254` — client pool (253 addresses)
- Allocation: query DB for in-use IPs, assign lowest available
- Release: on session expiry/revocation, IP becomes available

### 5.4 Key Management

- **Server keypair**: Generated once at first startup, stored in a file (`/data/wg_private.key`). The public key is derived at runtime.
- **Client keypairs**: Generated by the client. Server never sees the private key.
- No PSK mechanism for sessions (we use peer add/remove instead — simpler, equally secure for our scope).

---

## 6. Data Model

### 6.1 Entity-Relationship

```
User 1──────* Device
User 1──────1 TOTPSecret
User 1──────* VPNSession
Device 1────* VPNSession
```

### 6.2 Tables

#### `users`
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default uuid4 |
| username | VARCHAR(50) | UNIQUE, NOT NULL |
| password_hash | VARCHAR(255) | NOT NULL |
| is_admin | BOOLEAN | DEFAULT false, NOT NULL |
| is_active | BOOLEAN | DEFAULT true |
| created_at | DATETIME | NOT NULL |
| updated_at | DATETIME | NOT NULL |

**Admin seeding:** The first admin user is created at startup from environment variables `VPN_ADMIN_USERNAME` and `VPN_ADMIN_PASSWORD`. If these are set and the user doesn't exist, it is created with `is_admin=true` and a pre-generated TOTP secret (logged to console on first run for enrollment). This is explicit and reproducible for demos.

#### `totp_secrets`
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| user_id | UUID | FK → users.id, UNIQUE |
| encrypted_secret | VARCHAR(255) | NOT NULL |
| is_verified | BOOLEAN | DEFAULT false |
| created_at | DATETIME | NOT NULL |

#### `devices`
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| user_id | UUID | FK → users.id |
| name | VARCHAR(100) | NOT NULL |
| public_key | VARCHAR(44) | NOT NULL, UNIQUE |
| created_at | DATETIME | NOT NULL |
| last_active_at | DATETIME | NULL |

#### `vpn_sessions`
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| user_id | UUID | FK → users.id |
| device_id | UUID | FK → devices.id |
| assigned_ip | VARCHAR(18) | NOT NULL, UNIQUE among active |
| status | ENUM('active','expired','revoked') | NOT NULL |
| created_at | DATETIME | NOT NULL |
| expires_at | DATETIME | NOT NULL |
| revoked_at | DATETIME | NULL |

#### `system_settings`
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PK, DEFAULT 1, CHECK(id=1) |
| max_sessions_per_user | INTEGER | NOT NULL, DEFAULT 1 |
| session_ttl_hours | INTEGER | NOT NULL, DEFAULT 8 |
| updated_at | DATETIME | NOT NULL |

**Singleton pattern:** The `CHECK(id=1)` constraint ensures only one row exists. Created at DB initialization with defaults. Updated via admin API.

**Session limit enforcement:** When creating a VPN session (`POST /api/v1/vpn/sessions`), the server counts active sessions for the user. If `count >= max_sessions_per_user`, the request is rejected with `409 Conflict`:
```json
{
  "detail": "Session limit reached. Maximum 1 active session(s) allowed. Revoke an existing session first."
}
```

### 6.3 Indexes

- `users.username` — unique index (login lookup)
- `totp_secrets.user_id` — unique index
- `devices.public_key` — unique index
- `devices(user_id, name)` — unique index (one device name per user)
- `vpn_sessions.status` — partial index on `active` (session cleanup queries)
- `vpn_sessions(user_id, status)` — composite index (list user's active sessions)

---

## 7. Database Selection

### Decision: SQLite with WAL mode

**Rationale:**

| Criterion | SQLite | PostgreSQL |
|-----------|--------|-----------|
| Deployment complexity | Zero — single file | Requires separate container |
| Concurrent reads | Excellent (WAL mode) | Excellent |
| Concurrent writes | Adequate (single-writer, ~ms latency) | Excellent |
| Backup | Copy one file | pg_dump or volume snapshot |
| Diploma demo | `docker compose up` and done | Extra container to manage |
| Our write volume | Low (~10 users, ~1 write/min) | Overkill |

SQLite in WAL mode handles our concurrency needs. We're a single-server deployment with low write volume. The main writes are session creation/expiry — well within SQLite's capabilities.

**ORM: SQLAlchemy 2.0** with async support via `aiosqlite`.

**Migration: Alembic** — even for SQLite, we want schema versioning for reproducibility.

**Where data lives:** SQLite file at `/data/vpnservice.db` (Docker volume mount).

---

## 8. Security Considerations

### 8.1 Password Handling
- **Algorithm**: Argon2id (via `argon2-cffi`)
- **Why not bcrypt**: Argon2 is the modern standard (PHC winner), memory-hard, better GPU resistance
- Passwords validated for minimum length (8 chars) at API level

### 8.2 JWT Tokens
- **Library**: PyJWT
- **Signing**: HS256 with a server secret (from config/env)
- **Two token types:**
  - Intermediate token: `{"sub": user_id, "scope": "totp_verify", "exp": +5min}`
  - Access token: `{"sub": user_id, "scope": "full", "is_admin": bool, "exp": +24h}`
- Tokens are stateless — no server-side token storage
- Token refresh: not implemented (user re-authenticates when token expires)

### 8.3 TOTP Secrets
- Stored encrypted in the database using Fernet symmetric encryption
- Encryption key derived from a server secret (separate from JWT secret)
- TOTP window: allow ±1 time step (30s) to handle clock drift

### 8.4 WireGuard Key Management
- Server private key: stored in a file, not in the database
- File permissions: `0600`, owned by the service user
- Client private keys: never touch the server

### 8.5 Admin Authorization
- Admin user is seeded at startup via `VPN_ADMIN_USERNAME` + `VPN_ADMIN_PASSWORD` environment variables
- Admin flag stored as `is_admin` boolean in the users table
- JWT payload includes `is_admin: true` for admin users
- Admin endpoints protected by `require_admin` FastAPI dependency that:
  1. Runs `get_current_user` (validates JWT, extracts user)
  2. Checks `user.is_admin == True`
  3. Returns `403 Forbidden` if not admin
- Regular users cannot escalate to admin — there is no self-service admin promotion endpoint

### 8.6 Network Security
- **HTTPS mandatory**: Caddy reverse proxy terminates TLS on ports 443/80 (80 redirects to HTTPS)
- API server (uvicorn) listens on port `8000` internally — **not exposed** outside Docker network
- WireGuard listens on UDP `51820` — exposed directly (UDP, no TLS needed — WireGuard has its own encryption)
- Only ports 443, 80, and 51820/udp are exposed from Docker Compose
- The SQLite database is internal (Docker volume, not exposed)
- For local dev/demo, Caddy uses self-signed certificates or a local domain via its built-in CA

### 8.7 Input Validation
- All inputs validated via Pydantic models
- Public keys validated for WireGuard format (44 chars, valid base64)
- Rate limiting on auth endpoints (optional, via `slowapi` if time permits)

---

## 9. Deployment Architecture

### 9.1 Docker Compose

```yaml
services:
  caddy:
    image: caddy:2
    ports:
      - "443:443"
      - "80:80"          # Redirects to HTTPS
    volumes:
      - caddy-data:/data
      - ./Caddyfile:/etc/caddy/Caddyfile
    depends_on:
      - vpn-server
    restart: unless-stopped

  vpn-server:
    build: .
    cap_add:
      - NET_ADMIN        # Required for WireGuard
    sysctls:
      - net.ipv4.ip_forward=1
    expose:
      - "8000"           # Internal only — Caddy proxies to this
    ports:
      - "51820:51820/udp"  # WireGuard (direct, not proxied)
    volumes:
      - vpn-data:/data   # SQLite DB + WireGuard keys
    environment:
      - VPN_SECRET_KEY=...
      - VPN_JWT_SECRET=...
      - VPN_WG_ENDPOINT=server-public-ip:51820
      - VPN_WG_SUBNET=10.10.0.0/24
      - VPN_ADMIN_USERNAME=admin
      - VPN_ADMIN_PASSWORD=...
    restart: unless-stopped

volumes:
  vpn-data:
  caddy-data:
```

### 9.2 Caddyfile

```
# Production (with real domain):
vpn.example.com {
    reverse_proxy vpn-server:8000
}

# Local dev/demo (self-signed):
# :443 {
#     tls internal
#     reverse_proxy vpn-server:8000
# }
```

Caddy automatically provisions TLS certificates via Let's Encrypt for real domains. For local development, `tls internal` generates a self-signed certificate from Caddy's built-in CA.

### 9.3 Container Structure

Two containers:

**caddy** — TLS termination and reverse proxy:
- Handles HTTPS on 443, HTTP→HTTPS redirect on 80
- Proxies all API traffic to `vpn-server:8000` over internal Docker network
- Automatic certificate management

**vpn-server** — Application and WireGuard:
- FastAPI application (uvicorn) on port 8000 (HTTP, internal only)
- Background task thread for session cleanup
- WireGuard interface (kernel module on host, userspace tools in container)

**Why two containers instead of one:** Caddy is a standard reverse proxy image — no custom build needed. Separating TLS termination from application logic is a security best practice. The API server never handles raw TLS.

### 9.4 Dockerfile — Server (`Dockerfile`)

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y wireguard-tools iproute2
# ... install Python deps, copy code
CMD ["uvicorn", "vpnservice.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

The container needs:
- `wireguard-tools` — `wg` command
- `iproute2` — `ip` command
- `NET_ADMIN` capability — to create/manage network interfaces
- Host must have WireGuard kernel module loaded (`modprobe wireguard`)

### 9.5 Dockerfile — CLI (`Dockerfile.cli`)

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y wireguard-tools iproute2
# ... install Python deps, copy CLI code
ENTRYPOINT ["vpncli"]
```

Usage:
```bash
# Interactive connect:
docker run --rm -it --cap-add NET_ADMIN \
  vpncli connect --server https://vpn.example.com

# Or as a docker-compose service:
# services:
#   vpn-client:
#     build:
#       context: .
#       dockerfile: Dockerfile.cli
#     cap_add:
#       - NET_ADMIN
#     command: ["connect", "--server", "https://vpn.example.com"]
```

The CLI container requires `NET_ADMIN` capability and `wireguard-tools` to manage the WireGuard tunnel interface inside the container.

### 9.6 Data Persistence

| Data | Location | Persistence |
|------|----------|-------------|
| SQLite database | `/data/vpnservice.db` | Docker volume (`vpn-data`) |
| WireGuard server key | `/data/wg_private.key` | Docker volume (`vpn-data`) |
| Caddy TLS certificates | `/data/` | Docker volume (`caddy-data`) |
| Application config | Environment variables | docker-compose.yml |

---

## 10. CLI Client Design

### 10.1 Overview

A Python CLI tool (`vpncli`) that automates the full authentication and tunnel setup flow. Packaged as a Docker image for consistent deployment.

### 10.2 Packaging

**Docker image** (`Dockerfile.cli`):
- Based on `python:3.12-slim` with `wireguard-tools` and `iproute2`
- Entrypoint: `vpncli`
- Requires `NET_ADMIN` capability (to create WireGuard interface)

**Usage:**
```bash
# One-shot connect:
docker run --rm -it --cap-add NET_ADMIN vpncli connect --server https://vpn.example.com

# As a service in docker-compose:
services:
  vpn-client:
    build:
      context: .
      dockerfile: Dockerfile.cli
    cap_add:
      - NET_ADMIN
    command: ["connect", "--server", "https://vpn.example.com"]
```

### 10.3 Commands

```
vpncli register --server <url> --username <name>
vpncli login --server <url> --username <name>
vpncli connect --server <url> [--device-name <name>]
vpncli disconnect
vpncli status
vpncli sessions list --server <url>
vpncli sessions revoke --server <url> --session-id <id>
```

### 10.4 `connect` Flow (Main Command)

1. Check for existing valid access token (stored locally in `~/.vpncli/tokens.json`)
2. If no valid token: run login flow (prompt password → prompt TOTP)
3. Generate WireGuard keypair (ephemeral, per-session)
4. `POST /api/v1/vpn/sessions` with public key
5. Write WireGuard config to temp file
6. Bring up tunnel: `wg-quick up <config>`
7. Print status: assigned IP, expiry time
8. On `disconnect` or Ctrl+C: `wg-quick down`, `DELETE /api/v1/vpn/sessions/{id}`

### 10.5 Local Storage

- `~/.vpncli/tokens.json` — saved access tokens (per server)
- WireGuard configs are ephemeral (temp files, deleted after use)
- Client private keys are ephemeral (generated per session, never stored)
- When running in Docker, token storage is ephemeral unless a volume is mounted

---

## 11. Project Directory Structure

```
src/
├── vpnservice/              # Server package
│   ├── __init__.py
│   ├── main.py              # FastAPI app creation, lifespan, middleware
│   ├── config.py            # Pydantic Settings
│   ├── models.py            # SQLAlchemy ORM models
│   ├── database.py          # DB engine, session factory
│   ├── dependencies.py      # FastAPI dependencies (get_db, get_current_user, require_admin)
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── router.py        # Auth API routes
│   │   ├── schemas.py       # Pydantic request/response models
│   │   ├── service.py       # Auth business logic
│   │   └── jwt.py           # JWT creation/validation
│   ├── totp/
│   │   ├── __init__.py
│   │   ├── router.py        # TOTP API routes
│   │   ├── schemas.py       # Pydantic models
│   │   └── service.py       # TOTP business logic (pyotp)
│   ├── vpn/
│   │   ├── __init__.py
│   │   ├── router.py        # VPN session API routes
│   │   ├── schemas.py       # Pydantic models
│   │   └── service.py       # Session business logic
│   ├── admin/
│   │   ├── __init__.py
│   │   ├── router.py        # Admin API routes
│   │   ├── schemas.py       # Admin request/response models
│   │   └── service.py       # Admin business logic
│   ├── wireguard/
│   │   ├── __init__.py
│   │   ├── manager.py       # WireGuardManager class
│   │   └── schemas.py       # WireGuard data models (PeerStats, etc.)
│   └── tasks/
│       ├── __init__.py
│       └── cleanup.py       # Session expiry background task
├── vpncli/                  # CLI client package
│   ├── __init__.py
│   ├── main.py              # CLI entry point (click/typer)
│   ├── api_client.py        # HTTP client for API calls
│   ├── auth.py              # Login/register flow
│   ├── tunnel.py            # WireGuard tunnel management
│   └── config.py            # CLI configuration
├── alembic/                 # Database migrations
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
├── tests/                   # Test suite
│   ├── conftest.py
│   ├── test_auth/
│   ├── test_totp/
│   ├── test_vpn/
│   ├── test_admin/
│   └── test_wireguard/
├── Dockerfile               # Server image
├── Dockerfile.cli           # CLI client image
├── Caddyfile                # Caddy reverse proxy config
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## 12. Technology Choices Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python 3.12 | Diploma requirement, modern features |
| API framework | FastAPI | Async, auto-docs (Swagger), Pydantic integration |
| Database | SQLite + WAL | Zero-ops, sufficient for scope, single-file backup |
| ORM | SQLAlchemy 2.0 | Industry standard, async support |
| Migrations | Alembic | Schema versioning, reproducible setup |
| Password hashing | Argon2id | PHC winner, memory-hard |
| TOTP | pyotp | Standard library for RFC 6238 |
| JWT | PyJWT | Lightweight, well-maintained |
| TOTP secret encryption | cryptography (Fernet) | Symmetric encryption for at-rest secrets |
| WireGuard mgmt | subprocess (`wg`, `ip`) | Direct CLI calls, no extra dependencies |
| CLI framework | Typer | Modern, type-hint based, good UX |
| HTTP client (CLI) | httpx | Async-capable, modern API |
| TLS termination | Caddy 2 | Automatic HTTPS, zero-config certs, simple reverse proxy |
| Deployment | Docker Compose | Single `docker compose up` demo |
| QR codes | qrcode + Pillow | For TOTP enrollment QR generation |

---

## 13. Parallel Work Plan for Coders

### Shared Scaffolding (created before coders start)

These files must exist as skeletons so all coders can import from them:

- `src/vpnservice/__init__.py`
- `src/vpnservice/config.py` — full Pydantic settings class (including `VPN_ADMIN_USERNAME`, `VPN_ADMIN_PASSWORD`)
- `src/vpnservice/models.py` — all SQLAlchemy models (including `is_admin` on User, `SystemSettings` model)
- `src/vpnservice/database.py` — engine + session factory
- `src/vpnservice/dependencies.py` — `get_db`, `get_current_user`, `require_admin`
- `src/vpnservice/main.py` — FastAPI app skeleton with router includes (including admin router)
- `src/pyproject.toml` — all dependencies
- `src/Caddyfile` — Caddy reverse proxy configuration
- `src/Dockerfile.cli` — CLI Docker image

### Coder 1: "Auth" — Authentication, TOTP, admin, and core setup

**Scope:** Everything related to user identity, authentication, TOTP, and admin management.

**Files owned:**
- `src/vpnservice/auth/` (entire directory)
- `src/vpnservice/totp/` (entire directory)
- `src/vpnservice/admin/` (entire directory)

**Interfaces produced:**
- `get_current_user` dependency (JWT validation) — defined in `dependencies.py` (shared scaffold)
- `require_admin` dependency — defined in `dependencies.py` (shared scaffold)
- `User` model — defined in `models.py` (shared scaffold)
- Auth router mounted at `/api/v1/auth`
- TOTP router mounted at `/api/v1/auth/totp`
- Admin router mounted at `/api/v1/admin`

**Interfaces consumed:**
- `models.py`, `database.py`, `config.py` (from shared scaffold)
- `VPNSession` model (from shared scaffold) — needed for admin session listing
- `WireGuardManager.remove_peer()` — called when admin force-revokes a session (interface defined by architect, implemented by Coder 2)

**What to build:**
1. Auth service: register, login (password verification, intermediate JWT)
2. TOTP service: secret generation, QR code creation, code verification, enrollment confirmation
3. JWT service: token creation (intermediate + full access, includes `is_admin` claim), token validation
4. Auth router: `POST /register`, `POST /login`
5. TOTP router: `POST /totp/verify`
6. Password hashing with argon2
7. Admin service: list users, list all sessions, force-revoke session, get/update system settings
8. Admin router: all `/api/v1/admin/*` endpoints
9. Admin seeding at startup (in `main.py` lifespan or service init)

### Coder 2: "VPN" — VPN sessions, WireGuard management, and cleanup

**Scope:** Everything related to VPN session management and WireGuard interface control.

**Files owned:**
- `src/vpnservice/vpn/` (entire directory)
- `src/vpnservice/wireguard/` (entire directory)
- `src/vpnservice/tasks/` (entire directory)

**Interfaces produced:**
- VPN session router mounted at `/api/v1/vpn`
- `WireGuardManager` class

**Interfaces consumed:**
- `get_current_user` dependency (from shared scaffold, implemented by Coder 1)
- `User`, `Device`, `VPNSession`, `SystemSettings` models (from shared scaffold)
- `models.py`, `database.py`, `config.py` (from shared scaffold)

**What to build:**
1. WireGuard manager: add/remove peers, get stats, initialize interface
2. VPN session service: create session (allocate IP, add peer), list sessions, revoke session
3. **Session limit enforcement**: check active session count against `SystemSettings.max_sessions_per_user` before creating a session
4. IP address allocator (within VPN service)
5. Session cleanup background task
6. VPN router: `POST /sessions`, `GET /sessions`, `GET /sessions/{id}`, `DELETE /sessions/{id}`
7. Health endpoint: `GET /health`

### Coder 3: "CLI" — Command-line client (Docker-packaged)

**Scope:** The client-side CLI tool, packaged as a Docker image.

**Files owned:**
- `src/vpncli/` (entire directory)

**Interfaces produced:**
- `vpncli` Docker image / executable

**Interfaces consumed:**
- REST API contract (from this design doc — no code dependency on server)

**What to build:**
1. API client: HTTP calls to all server endpoints
2. Auth flow: register, login with TOTP prompt
3. Tunnel management: generate keypair, write wg config, bring up/down via `wg-quick`
4. Token storage: save/load tokens from `~/.vpncli/`
5. CLI commands: register, login, connect, disconnect, status, sessions

### Integration Order

1. **First: Shared scaffold** — architect creates skeleton files (including Caddyfile, Dockerfile.cli)
2. **Parallel: Coder 1 (Auth+Admin) + Coder 2 (VPN) + Coder 3 (CLI)** — all three can work simultaneously
3. **Merge order:**
   - Merge Coder 1 first (auth has no dependencies on VPN)
   - Merge Coder 2 second (VPN imports `get_current_user` from auth — but this is in the shared scaffold, so the actual implementation just needs to exist)
   - Merge Coder 3 last (CLI is fully independent, but manual testing requires server to be running)
4. **Integration test:** After all three merged, do end-to-end test

### Cross-coder dependency: Admin session revocation

When an admin force-revokes a session (`DELETE /api/v1/admin/sessions/{id}`), the admin service (Coder 1) must remove the WireGuard peer (Coder 2's `WireGuardManager`). This is handled via the shared interface:

```python
# Coder 1 calls this in admin/service.py:
await wireguard_manager.remove_peer(session.client_public_key)
```

The `WireGuardManager` instance is injected via FastAPI dependency injection (defined in shared scaffold). Both coders code against the architect-defined interface — no direct dependency between their code.

---

## 14. Context for Tester

### What to test against

The system has four testable boundaries:

1. **Auth module** — registration, login, TOTP enrollment/verification, JWT issuance
   - Expected behavior: users register → get TOTP secret → verify code → login with password → verify TOTP → get access token
   - Edge cases: duplicate username, wrong password, wrong TOTP code, expired intermediate token, TOTP not yet enrolled
   - The auth module is pure business logic + DB — no WireGuard dependency, fully testable with an in-memory SQLite

2. **VPN session module** — session CRUD, IP allocation, session lifecycle, session limits
   - Expected behavior: authenticated user creates session → gets config → session expires → peer removed
   - Edge cases: no IPs available, duplicate device, session already expired, WireGuard interface down, **session limit reached (409)**
   - Session limit enforcement: creating a session when `active_count >= max_sessions_per_user` must return 409
   - WireGuard calls should be mockable (the `WireGuardManager` class is the boundary)

3. **Admin module** — user listing, session management, system settings
   - Expected behavior: admin can list all users, list/revoke all sessions, update settings
   - Edge cases: non-admin user trying admin endpoints (403), updating settings with invalid values (422), revoking already-expired session
   - Admin seeding: verify admin user is created from env vars at startup
   - `require_admin` dependency: verify it blocks non-admin users

4. **API integration** — full request/response cycle through FastAPI
   - Test with `TestClient` (httpx)
   - Verify auth middleware, admin middleware, error responses, correct status codes
   - Full flows: register → login → TOTP → create session → revoke session
   - Admin flows: admin login → list users → update settings → force-revoke session

### What NOT to test (out of scope for unit/integration tests)
- Actual WireGuard kernel operations (require root + kernel module)
- CLI tunnel management (requires real WireGuard)
- These are validated manually during the demo

### Key interfaces to test against
- All API endpoints from Sections 4.1–4.5 (including admin endpoints)
- `WireGuardManager` class interface from Section 5.2
- JWT token scopes and expiry behavior from Section 8.2 (including `is_admin` claim)
- Session state machine from Section 3.4
- Session limit enforcement from Section 6.2 (`system_settings` table)
- Admin authorization (`require_admin` dependency) from Section 8.5

---

## 15. Alternatives Considered

### PSK-as-session-token (DefGuard approach)
- **Pros:** Cryptographic binding of session to tunnel, no peer add/remove overhead
- **Cons:** More complex (PSK rotation, key delivery), harder to explain in thesis, requires client-side PSK handling
- **Decision:** Peer add/remove is simpler, equally effective for our scope, and easier to reason about

### PostgreSQL
- **Pros:** Battle-tested, better concurrency, richer features
- **Cons:** Extra container, more operational complexity
- **Decision:** SQLite is sufficient for single-node diploma deployment

### OAuth2/OIDC for auth
- **Pros:** Industry standard, extensible
- **Cons:** Requires external IdP or complex implementation, defeats purpose of building our own 2FA
- **Decision:** Custom auth with JWT keeps system self-contained

### wgconfig Python library
- **Pros:** Pythonic API for WireGuard config
- **Cons:** Manages config files, not live interface state; we need runtime peer management
- **Decision:** Direct `wg` CLI calls give us real-time control

---

## 16. Open Questions

1. **Admin TOTP enrollment flow:** When admin is seeded via env vars, how does the admin enroll TOTP? Current plan: log the TOTP secret/URI to console on first run. The admin must scan it before first login. Is this sufficient, or should there be an "admin bootstrap" mode that skips TOTP for initial setup?
2. **Session limit edge case:** When admin lowers `max_sessions_per_user` below the current active count for some users, should existing sessions be force-revoked, or just prevent new ones? Current plan: only prevent new sessions — don't retroactively revoke.
3. **Caddy certificate for demo:** For the diploma defense demo, should we use `tls internal` (self-signed) or set up a local domain? Self-signed requires the CLI to accept untrusted certs (`--insecure` flag or custom CA trust).

---

## Changelog

- 2026-03-09: Add HTTPS (Caddy), admin role, session limits, Docker CLI packaging — resolved open questions
- 2026-03-08: Initial architecture draft — full system design
