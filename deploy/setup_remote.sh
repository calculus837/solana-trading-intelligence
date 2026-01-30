#!/bin/bash
# Independent script to provision a fresh Ubuntu 22.04 server for Solana Intel Engine.
# This script is copied to the server and run by deploy.sh.

set -e

APP_DIR="/opt/solana-intel-engine"
USER_NAME="intel"

echo "RESOURCE: Provisioning server..."

# 1. Install Docker if missing
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
    echo "Docker already installed."
fi

# 2. Setup User permissions
if ! id "$USER_NAME" &>/dev/null; then
    sudo useradd -m -s /bin/bash $USER_NAME
    sudo usermod -aG docker $USER_NAME
    echo "Created user $USER_NAME and added to docker group."
fi

# 3. Create App Directory
sudo mkdir -p $APP_DIR
sudo chown -R $USER:$USER $APP_DIR
sudo chmod -R 755 $APP_DIR

sudo chmod -R 755 $APP_DIR

# 4. Configure Swap Space (8GB) - Critical for Neo4j/Redis stability
if [ ! -f /swapfile ]; then
    echo "Creating 8GB Swap File..."
    sudo fallocate -l 8G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    
    # Tuning Swap Swappiness (Use RAM first, swap only when necessary)
    sudo sysctl vm.swappiness=10
    echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
else
    echo "Swap file already exists."
fi

echo "Server provisioned successfully. Ready for code sync."
