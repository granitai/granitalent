#!/bin/bash
# =============================================================
# Granitalent VPS Deployment Script
# Run this on the VPS: bash deploy.sh
# =============================================================

set -e

DOMAIN="talents.granitai.com"
EMAIL="${DEPLOY_EMAIL:-admin@granitai.com}"  # Override with: DEPLOY_EMAIL=you@example.com bash deploy.sh

echo "============================================"
echo "  Granitalent Production Deployment"
echo "  Domain: $DOMAIN"
echo "============================================"

# ----------------------------------------------------------
# Step 1: Check prerequisites
# ----------------------------------------------------------
echo ""
echo "[1/5] Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. Please log out and back in, then re-run this script."
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "Docker Compose not found. Installing plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

# Use 'docker compose' (plugin) or 'docker-compose' (standalone)
if docker compose version &> /dev/null 2>&1; then
    DC="docker compose"
else
    DC="docker-compose"
fi

echo "Using: $DC"

# ----------------------------------------------------------
# Step 2: Ensure backend/.env exists
# ----------------------------------------------------------
echo ""
echo "[2/5] Checking environment configuration..."

if [ ! -f backend/.env ]; then
    echo "ERROR: backend/.env not found!"
    echo "Copy backend/.env.example to backend/.env and fill in your API keys."
    exit 1
fi

echo "backend/.env found."

# ----------------------------------------------------------
# Step 3: Initial SSL certificate setup
# ----------------------------------------------------------
echo ""
echo "[3/5] Setting up SSL certificates..."

# Use initial (HTTP-only) nginx config for ACME challenge
cp nginx/conf.d/app.conf.initial nginx/conf.d/app.conf

# Start services with HTTP-only config
$DC -f docker-compose.prod.yml up -d --build backend frontend nginx

echo "Waiting for nginx to start..."
sleep 5

# Request certificate
echo "Requesting Let's Encrypt certificate for $DOMAIN..."
$DC -f docker-compose.prod.yml run --rm certbot \
    certbot certonly \
    --webroot \
    -w /var/www/certbot \
    -d "$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    --force-renewal

# ----------------------------------------------------------
# Step 4: Switch to full SSL config
# ----------------------------------------------------------
echo ""
echo "[4/5] Enabling HTTPS configuration..."

cp nginx/conf.d/app.conf.ssl nginx/conf.d/app.conf

# Restart nginx with SSL config
$DC -f docker-compose.prod.yml restart nginx

# Start certbot auto-renewal daemon
$DC -f docker-compose.prod.yml up -d certbot

# ----------------------------------------------------------
# Step 5: Verify
# ----------------------------------------------------------
echo ""
echo "[5/5] Verifying deployment..."
sleep 3

if curl -s -o /dev/null -w "%{http_code}" "https://$DOMAIN" | grep -q "200\|301\|302"; then
    echo ""
    echo "============================================"
    echo "  Deployment successful!"
    echo "  https://$DOMAIN"
    echo "============================================"
else
    echo ""
    echo "WARNING: Could not verify HTTPS access."
    echo "Check that DNS is pointed to this server."
    echo "You can check logs with:"
    echo "  $DC -f docker-compose.prod.yml logs nginx"
    echo "  $DC -f docker-compose.prod.yml logs backend"
fi

echo ""
echo "Useful commands:"
echo "  Logs:     $DC -f docker-compose.prod.yml logs -f"
echo "  Stop:     $DC -f docker-compose.prod.yml down"
echo "  Restart:  $DC -f docker-compose.prod.yml restart"
echo "  Rebuild:  $DC -f docker-compose.prod.yml up -d --build"
