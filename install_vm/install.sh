#!/bin/bash

# Install script for jbsays project on Ubuntu VM
# This script installs all required dependencies

set -e  # Exit on error

echo "=== JBSays Installation Script ==="
echo "Ubuntu $(lsb_release -rs) detected"
echo ""

# Update package lists
echo "Updating package lists..."
sudo apt update

# Install basic build tools
echo ""
echo "Installing build tools..."
sudo apt install -y build-essential gcc make curl wget

# Install Python and pip
echo ""
echo "Installing Python dependencies..."
sudo apt install -y python3 python3-pip python3-venv

# Install Git (should already be installed based on diag)
echo ""
echo "Ensuring Git is installed..."
sudo apt install -y git

# Install Docker
echo ""
echo "Installing Docker..."
# Remove old versions if any
sudo apt remove -y docker docker-engine docker.io containerd runc || true

# Install dependencies
sudo apt install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# Add Docker's official GPG key
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Set up the repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add current user to docker group
echo ""
echo "Adding user to docker group..."
sudo usermod -aG docker $USER
echo "NOTE: You'll need to log out and back in for docker group changes to take effect"

# Install Docker Compose standalone (v1 compatibility)
echo ""
echo "Installing Docker Compose standalone..."
sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Install Node.js and npm
echo ""
echo "Installing Node.js and npm..."
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Install Python packages for telegram bot
echo ""
echo "Installing Python packages for telegram bot..."
pip3 install --user -r requirements_telegram_bot.txt

# Create necessary directories
echo ""
echo "Creating project directories..."
mkdir -p logs .jbsays/config .telegram_inbox_bot/processed

# Set up telegram bot config if needed
if [ ! -f telegram_bot_config.json ] && [ -f telegram_bot_config.json.sample ]; then
    echo ""
    echo "Setting up telegram bot configuration..."
    cp telegram_bot_config.json.sample telegram_bot_config.json
    echo "NOTE: Edit telegram_bot_config.json to add your allowed user IDs"
fi

# Make scripts executable
echo ""
echo "Setting script permissions..."
chmod +x *.sh jbsays extensions/entrypoint.sh

# Build Docker images
echo ""
echo "Building Docker images..."
echo "Building main jbsays image..."
docker build . -t jbsays:latest

# Start Docker service
echo ""
echo "Starting Docker service..."
sudo systemctl start docker
sudo systemctl enable docker

# Run diagnostic to verify installation
echo ""
echo "Running post-installation diagnostic..."
./diag.sh

