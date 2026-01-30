#!/bin/bash
# Master deployment script.
# Usage: ./deploy.sh user@host

set -e

if [ -z "$1" ]; then
    echo "Usage: ./deploy.sh user@host"
    exit 1
fi

REMOTE="$1"
APP_DIR="/opt/solana-intel-engine"
DEPLOY_KEY="deploy_key"

echo "🚀 Deploying to $REMOTE..."

# 1. Provision Server (Install Docker etc)
echo "📦 Provisioning remote server..."
scp deploy/setup_remote.sh $REMOTE:/tmp/setup_remote.sh
ssh $REMOTE "chmod +x /tmp/setup_remote.sh && sudo /tmp/setup_remote.sh"

# 2. Sync Code
echo "🔄 Syncing code..."
rsync -avz --delete \
    --exclude '.git' \
    --exclude '.env' \
    --exclude '__pycache__' \
    --exclude '.venv' \
    --exclude 'logs' \
    --exclude 'data' \
    ./ $REMOTE:$APP_DIR/

# 3. Remote Build & Launch
echo "🔥 Launching services..."
ssh $REMOTE "cd $APP_DIR && \
    if [ ! -f .env ]; then echo 'WARNING: .env missing on production!'; fi && \
    docker compose up -d --build --force-recreate"

echo "✅ Deployment complete!"
echo "   Monitor logs using: ssh $REMOTE 'cd $APP_DIR && docker compose logs -f'"
