#!/bin/bash
# GEO Checker deployment script
set -e

cd /opt/geo-checker

echo "==> Pulling latest code from GitHub..."
git pull

echo "==> Building Docker image..."
docker compose build

echo "==> Starting container..."
docker compose up -d

echo "==> Deployment complete!"
docker ps | grep geo-checker
