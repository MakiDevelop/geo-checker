#!/bin/bash
# GEO Checker deployment script
set -e

cd /opt/abd/ABD

echo "==> Pulling latest code from GitHub..."
git pull

echo "==> Building Docker image..."
cd geo-checker
docker compose build

echo "==> Starting container..."
docker compose up -d

echo "==> Deployment complete!"
docker ps | grep geo-checker
