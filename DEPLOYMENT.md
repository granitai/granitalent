# Deployment Guide

This project supports two deployment modes: **local development** and **production VPS** with SSL.

---

## Local Development

Uses the same setup as before. No SSL, no reverse proxy — just backend + frontend.

```bash
# Option 1: Use the original docker-compose.yml (unchanged)
docker-compose up --build

# Option 2: Use the explicit local file
docker-compose -f docker-compose.local.yml up --build
```

- Frontend: `http://localhost:3034`
- Backend API: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`

For frontend dev server (hot reload):
```bash
cd frontend && npm run dev    # http://localhost:3000 — proxies to :8000
```

---

## Production VPS Deployment (talents.granitai.com)

### Prerequisites

- A VPS with Ubuntu/Debian (IP: `89.116.110.217`)
- Docker and Docker Compose installed on the VPS
- Domain `talents.granitai.com` pointing to the VPS (see DNS section below)
- `backend/.env` configured with all API keys

### Step 1: Configure DNS on Hostinger

Log in to [Hostinger DNS Zone Editor](https://hpanel.hostinger.com/domain/granitai.com/dns) for `granitai.com`:

| Type  | Name      | Value             | TTL  |
|-------|-----------|-------------------|------|
| A     | talents   | 89.116.110.217    | 3600 |

**How to add the record:**

1. Go to Hostinger hPanel → **Domains** → `granitai.com` → **DNS / Name Servers** → **DNS Records**
2. Click **Add Record**
3. Select type **A**
4. In **Name** (or Host), enter: `talents`
5. In **Points to** (or Value), enter: `89.116.110.217`
6. Set TTL to **3600** (or leave default)
7. Click **Add Record**

**No CNAME needed** — the A record is sufficient.

**Verify DNS propagation** (wait 5-15 minutes, can take up to 24h):
```bash
# From any machine
nslookup talents.granitai.com
# Should return 89.116.110.217

# Or use dig
dig talents.granitai.com +short
```

### Step 2: Transfer the project to VPS

```bash
# Option A: Git clone
ssh root@89.116.110.217
git clone <your-repo-url> /opt/granitalent
cd /opt/granitalent

# Option B: rsync from local machine
rsync -avz --exclude='node_modules' --exclude='.git' --exclude='*.db' \
  . root@89.116.110.217:/opt/granitalent/
ssh root@89.116.110.217
cd /opt/granitalent
```

### Step 3: Configure environment

```bash
cp backend/.env.example backend/.env
nano backend/.env
# Fill in all API keys: ELEVENLABS_API_KEY, GOOGLE_API_KEY, etc.
```

### Step 4: Configure firewall

```bash
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP (for Let's Encrypt + redirect)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

### Step 5: Deploy with SSL

**Automated (recommended):**
```bash
DEPLOY_EMAIL=your-email@example.com bash deploy.sh
```

**Manual step-by-step:**

```bash
# 1. Use HTTP-only nginx config (needed for Let's Encrypt challenge)
cp nginx/conf.d/app.conf.initial nginx/conf.d/app.conf

# 2. Build and start services
docker compose -f docker-compose.prod.yml up -d --build

# 3. Obtain SSL certificate
docker compose -f docker-compose.prod.yml run --rm certbot \
  certbot certonly --webroot \
  -w /var/www/certbot \
  -d talents.granitai.com \
  --email your-email@example.com \
  --agree-tos --no-eff-email

# 4. Switch to full SSL nginx config
cp nginx/conf.d/app.conf.ssl nginx/conf.d/app.conf

# 5. Restart nginx to load SSL config
docker compose -f docker-compose.prod.yml restart nginx

# 6. Start certbot auto-renewal
docker compose -f docker-compose.prod.yml up -d certbot
```

### Step 6: Verify

```bash
# Check all containers are running
docker compose -f docker-compose.prod.yml ps

# Test HTTPS
curl -I https://talents.granitai.com
```

Visit: **https://talents.granitai.com**

---

## File Structure

```
docker-compose.yml           # Original (works for both quick local and simple deploy)
docker-compose.local.yml     # Explicit local development config
docker-compose.prod.yml      # Production VPS with SSL (nginx + certbot)
deploy.sh                    # Automated production deployment script
nginx/
  conf.d/
    app.conf                 # Active nginx config (swapped during deploy)
    app.conf.initial         # HTTP-only config (for first certbot run)
    app.conf.ssl             # Full HTTPS config (restored after certbot)
```

---

## Useful Commands

### Production (VPS)

```bash
# View logs
docker compose -f docker-compose.prod.yml logs -f
docker compose -f docker-compose.prod.yml logs -f backend

# Restart
docker compose -f docker-compose.prod.yml restart

# Rebuild after code changes
docker compose -f docker-compose.prod.yml up -d --build

# Stop everything
docker compose -f docker-compose.prod.yml down

# Force SSL renewal
docker compose -f docker-compose.prod.yml run --rm certbot certbot renew --force-renewal
docker compose -f docker-compose.prod.yml restart nginx

# Shell into backend container
docker compose -f docker-compose.prod.yml exec backend bash
```

### Local

```bash
docker-compose up --build          # Start
docker-compose down                # Stop
docker-compose logs -f backend     # Logs
```

---

## Updating the VPS after code changes

```bash
ssh root@89.116.110.217
cd /opt/granitalent
git pull                                               # or rsync new files
docker compose -f docker-compose.prod.yml up -d --build
```

---

## Troubleshooting

### SSL certificate not obtained
- Verify DNS: `dig talents.granitai.com +short` must return `89.116.110.217`
- Ensure port 80 is open: `sudo ufw status`
- Check certbot logs: `docker compose -f docker-compose.prod.yml logs certbot`
- Make sure `app.conf.initial` is active (HTTP-only) during certificate request

### "Connection refused" on HTTPS
- Check nginx is running: `docker compose -f docker-compose.prod.yml ps`
- Check nginx logs: `docker compose -f docker-compose.prod.yml logs nginx`
- Verify port 443 is open: `sudo ufw allow 443/tcp`

### WebSocket not connecting
- The nginx config includes long timeouts (`proxy_read_timeout 3600s`) for `/ws`
- Check browser console for WebSocket errors
- Verify the backend is healthy: `curl http://localhost:8000/docs` from the VPS

### Frontend shows blank page
- Check frontend container: `docker compose -f docker-compose.prod.yml logs frontend`
- Verify the build succeeded during `docker compose up --build`

### Database issues
- Database is persisted in the `db-data` Docker volume
- To inspect: `docker compose -f docker-compose.prod.yml exec backend ls -la /app/backend/database.db`
