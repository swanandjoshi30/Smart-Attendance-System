#!/usr/bin/env bash

# Ensure apt runs without interactive prompts
export DEBIAN_FRONTEND=noninteractive
APT_OPTIONS="-o Dpkg::Options::='--force-confdef' -o Dpkg::Options::='--force-confold'"


# Setup script for smart-attendance system on a VPS (Ubuntu/Debian)
set -euo pipefail

echo "=========================================="
echo " Starting Smart Attendance VPS Setup Script"
echo "=========================================="

# 1. Swap Space Setup (Mandatory for servers with <= 2GB RAM to prevent OOM errors)
TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
TOTAL_RAM_GB=$((TOTAL_RAM_KB / 1024 / 1024))

echo "Detected System RAM: ${TOTAL_RAM_GB} GB"

if [ "$TOTAL_RAM_GB" -le 2 ]; then
    echo "System RAM is <= 2GB. Creating a 4GB Swap file to prevent compilation/memory crashes..."
    if [ ! -f /swapfile ]; then
        sudo fallocate -l 4G /swapfile
        sudo chmod 600 /swapfile
        sudo mkswap /swapfile
        sudo swapon /swapfile
        echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
        echo "✓ Swap space successfully configured!"
    else
        echo "Swap file already exists. Skipping creation."
    fi
else
    echo "System has sufficient RAM (${TOTAL_RAM_GB} GB). Skipping swap creation."
fi

# 2. Update System & Install Dependencies
echo "Updating packages..."
sudo apt-get $APT_OPTIONS update && sudo apt-get $APT_OPTIONS upgrade -y
sudo apt-get $APT_OPTIONS install -y curl git build-essential libgl1-mesa-glx libglib2.0-0

# 3. Install Docker & Docker Compose if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker "$USER"
    rm get-docker.sh
    echo "✓ Docker installed successfully!"
else
    echo "Docker is already installed."
fi

if ! command -v docker compose &> /dev/null; then
    echo "Installing Docker Compose..."
    sudo apt-get $APT_OPTIONS install -y docker-compose-plugin
    echo "✓ Docker Compose installed successfully!"
else
    echo "Docker Compose is already installed."
fi

# 4. Prompt configuration check
echo "=========================================="
echo "Please verify credentials in docker-compose.yml"
echo "before running: docker compose up --build -d"
echo "=========================================="
echo "Setup steps completed successfully!"
