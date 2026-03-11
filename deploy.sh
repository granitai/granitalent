#!/bin/bash
# =============================================================
# Granitalent VPS Deployment Script
# Uses existing Traefik reverse proxy on the "proxy" network
# Run this on the VPS: bash deploy.sh
# =============================================================

set -e

DOMAIN="talents.granitai.com"

echo "============================================"
echo "  Granitalent Production Deployment"
echo "  Domain: $DOMAIN"
echo "============================================"

# ----------------------------------------------------------
# Step 1: Check prerequisites
# ----------------------------------------------------------
echo ""
echo "[1/4] Checking prerequisites..."

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
echo "[2/4] Checking environment configuration..."

if [ ! -f backend/.env ]; then
    echo "ERROR: backend/.env not found!"
    echo "Copy backend/.env.example to backend/.env and fill in your API keys."
    exit 1
fi

echo "backend/.env found."

# ----------------------------------------------------------
# Step 3: Ensure Traefik proxy network exists
# ----------------------------------------------------------
echo ""
echo "[3/4] Checking Traefik proxy network..."

if ! docker network inspect proxy &> /dev/null; then
    echo "ERROR: Docker network 'proxy' not found!"
    echo "Traefik must be running with a 'proxy' network."
    echo "Make sure the company-profile-agent Traefik is up."
    exit 1
fi

echo "Traefik proxy network found."

# Clean up old nginx/certbot containers if they exist
if docker ps -a --format '{{.Names}}' | grep -q granitalent-nginx; then
    echo "Removing old nginx container..."
    docker stop granitalent-nginx 2>/dev/null || true
    docker rm granitalent-nginx 2>/dev/null || true
fi

if docker ps -a --format '{{.Names}}' | grep -q granitalent-certbot; then
    echo "Removing old certbot container..."
    docker stop granitalent-certbot 2>/dev/null || true
    docker rm granitalent-certbot 2>/dev/null || true
fi

# ----------------------------------------------------------
# Step 4: Build and deploy
# ----------------------------------------------------------
echo ""
echo "[4/4] Building and deploying..."

# Stop existing containers first to force Traefik to re-read labels
$DC -f docker-compose.prod.yml down 2>/dev/null || true

$DC -f docker-compose.prod.yml up -d --build

echo ""
echo "Waiting for services to start..."
sleep 10

echo ""
echo "Container status:"
docker ps --filter "name=granitalent" --format "table {{.Names}}\t{{.Status}}"

# ----------------------------------------------------------
# Verify
# ----------------------------------------------------------
echo "Verifying deployment..."

if curl -s -o /dev/null -w "%{http_code}" "https://$DOMAIN" | grep -q "200\|301\|302"; then
    echo ""
    echo "============================================"
    echo "  Deployment successful!"
    echo "  https://$DOMAIN"
    echo "============================================"
else
    echo ""
    echo "WARNING: Could not verify HTTPS access."
    echo "Traefik may need a moment to obtain the SSL certificate."
    echo "Check logs with:"
    echo "  $DC -f docker-compose.prod.yml logs backend"
    echo "  $DC -f docker-compose.prod.yml logs frontend"
    echo "  docker logs company-profile-agent-traefik-1"
fi

echo ""
echo "Useful commands:"
echo "  Logs:     $DC -f docker-compose.prod.yml logs -f"
echo "  Stop:     $DC -f docker-compose.prod.yml down"
echo "  Restart:  $DC -f docker-compose.prod.yml restart"
echo "  Rebuild:  $DC -f docker-compose.prod.yml up -d --build"
