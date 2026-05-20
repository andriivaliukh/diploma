# VPN Service with 2FA — Deployment Guide

## Prerequisites

- **Server**: Ubuntu 26.04 LTS (Resolute Raccoon) VPS (tested on UpCloud, works on any provider)
- **Resources**: 1 vCPU, 1 GB RAM minimum
- **Network**: Public IP address with ports 22, 80, 443 (TCP) and 51820 (UDP) available
- **Domain** (optional): DNS A-record pointing to the server IP (required for Let's Encrypt TLS)
- **SSH access**: Root or sudo-capable user

## Quick Start

### 1. Transfer project files to the server

From your local machine:

```bash
rsync -avz src/ root@YOUR_SERVER_IP:/opt/vpnservice/
rsync -avz deploy/setup.sh root@YOUR_SERVER_IP:/opt/vpnservice/setup.sh
```

### 2. Run the setup script

SSH into the server and execute:

```bash
ssh root@YOUR_SERVER_IP
chmod +x /opt/vpnservice/setup.sh
/opt/vpnservice/setup.sh vpn.example.com admin YourSecurePassword
```

The script will:
- Install Docker (if not present)
- Install WireGuard kernel tools
- Enable IP forwarding
- Configure UFW firewall (ports 22, 80, 443, 51820/udp)
- Generate cryptographic secrets (Fernet key, JWT secret)
- Write the `.env` configuration file

### 3. Start the service

```bash
cd /opt/vpnservice
docker compose --env-file .env up -d --build
```

First build takes 1–2 minutes. Subsequent restarts are instant.

### 4. Verify health

```bash
curl -k https://vpn.example.com/api/v1/health
```

Expected response:

```json
{"status": "healthy", "wireguard": "up", "version": "0.1.0"}
```

### 5. Register the first user

Use the CLI client or `curl`:

```bash
# Register
curl -k -X POST https://vpn.example.com/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "myuser", "password": "mypassword123"}'

# The response contains totp_secret and totp_uri — add to your authenticator app
# Then verify TOTP enrollment:
curl -k -X POST https://vpn.example.com/api/v1/auth/totp/verify \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth_token_from_register>" \
  -d '{"totp_code": "123456"}'
```

## TLS Configuration

### Self-signed (demo/testing)

The default configuration uses Caddy's built-in CA for self-signed certificates.
Keep `TLS_MODE=internal` in `.env`. Clients must use `-k` flag with curl or
accept the certificate warning.

### Let's Encrypt (production)

1. Point your domain DNS A-record to the server IP
2. Edit `/opt/vpnservice/.env`:
   ```
   VPN_DOMAIN=vpn.example.com
   TLS_MODE=
   ```
3. Restart: `docker compose --env-file .env up -d`

Caddy automatically provisions and renews Let's Encrypt certificates.

## Common Operations

### View logs

```bash
cd /opt/vpnservice
docker compose logs -f vpn-server    # Application logs
docker compose logs -f caddy          # Reverse proxy logs
```

### Restart the service

```bash
cd /opt/vpnservice
docker compose --env-file .env restart
```

### Update the application

```bash
rsync -avz src/ root@YOUR_SERVER_IP:/opt/vpnservice/
ssh root@YOUR_SERVER_IP "cd /opt/vpnservice && docker compose --env-file .env up -d --build"
```

### Backup data

```bash
# SQLite database and WireGuard keys are in the vpn-data Docker volume
docker compose stop vpn-server
docker cp $(docker compose ps -q vpn-server):/data /backup/vpnservice-data
docker compose start vpn-server
```

## Troubleshooting

### WireGuard interface not coming up

Check that the WireGuard kernel module is loaded on the host:

```bash
lsmod | grep wireguard
# If missing:
modprobe wireguard
```

Verify the container has NET_ADMIN capability (this is set in docker-compose.yml).

### Port 51820 not reachable

Check UFW status:

```bash
ufw status
```

Ensure your cloud provider's firewall/security group also allows UDP 51820 inbound.

### Caddy fails to get Let's Encrypt certificate

- Verify DNS A-record resolves to the server IP: `dig vpn.example.com`
- Ensure ports 80 and 443 are open (Let's Encrypt HTTP-01 challenge uses port 80)
- Check Caddy logs: `docker compose logs caddy`

### Database errors after upgrade

Run Alembic migrations inside the container:

```bash
docker compose exec vpn-server alembic upgrade head
```

### Container keeps restarting

Check logs for the crash reason:

```bash
docker compose logs --tail=50 vpn-server
```

Common causes:
- Missing environment variables in `.env`
- Port 51820 already in use by another WireGuard instance
- Insufficient permissions (NET_ADMIN capability missing)

## File Layout on Server

```
/opt/vpnservice/
├── .env                    # Server configuration (chmod 600)
├── docker-compose.yml      # Service definitions
├── Dockerfile              # API server image
├── Caddyfile               # Reverse proxy config
├── pyproject.toml          # Python dependencies
├── alembic.ini             # Migration config
├── alembic/                # Migration scripts
└── vpnservice/             # Application source code
```

Data is stored in Docker volumes:
- `vpn-data` — SQLite database + WireGuard server private key
- `caddy-data` — TLS certificates managed by Caddy
