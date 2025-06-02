#!/bin/bash

# Diagnostic script to check what's installed on the VM
# Run this on the target VM to see what needs to be installed

echo "=== System Diagnostic Report ==="
echo "Date: $(date)"
echo "Hostname: $(hostname)"
echo ""

echo "=== OS Information ==="
if [ -f /etc/os-release ]; then
    cat /etc/os-release | grep -E "^(NAME|VERSION|ID|ID_LIKE)="
else
    echo "OS release info not found"
fi
echo ""

echo "=== Docker Status ==="
if command -v docker &> /dev/null; then
    echo "Docker: INSTALLED"
    docker --version
    echo "Docker service status:"
    sudo systemctl is-active docker || echo "Docker service not running"
    echo "Current user in docker group:"
    groups | grep -q docker && echo "YES" || echo "NO"
else
    echo "Docker: NOT INSTALLED"
fi
echo ""

echo "=== Docker Compose Status ==="
if command -v docker-compose &> /dev/null; then
    echo "Docker Compose v1: INSTALLED"
    docker-compose --version
else
    echo "Docker Compose v1: NOT INSTALLED"
fi

if docker compose version &> /dev/null 2>&1; then
    echo "Docker Compose v2: INSTALLED"
    docker compose version
else
    echo "Docker Compose v2: NOT INSTALLED"
fi
echo ""

echo "=== Python Status ==="
if command -v python3 &> /dev/null; then
    echo "Python3: INSTALLED"
    python3 --version
else
    echo "Python3: NOT INSTALLED"
fi

if command -v pip3 &> /dev/null; then
    echo "pip3: INSTALLED"
    pip3 --version
else
    echo "pip3: NOT INSTALLED"
fi

if command -v python &> /dev/null; then
    echo "Python (default): $(python --version 2>&1)"
else
    echo "Python (default): NOT FOUND"
fi
echo ""

echo "=== Node.js Status ==="
if command -v node &> /dev/null; then
    echo "Node.js: INSTALLED"
    node --version
else
    echo "Node.js: NOT INSTALLED"
fi

if command -v npm &> /dev/null; then
    echo "npm: INSTALLED"
    npm --version
else
    echo "npm: NOT INSTALLED"
fi
echo ""

echo "=== Git Status ==="
if command -v git &> /dev/null; then
    echo "Git: INSTALLED"
    git --version
else
    echo "Git: NOT INSTALLED"
fi
echo ""

echo "=== Build Tools ==="
if command -v gcc &> /dev/null; then
    echo "gcc: INSTALLED ($(gcc --version | head -n1))"
else
    echo "gcc: NOT INSTALLED"
fi

if command -v make &> /dev/null; then
    echo "make: INSTALLED"
else
    echo "make: NOT INSTALLED"
fi

if dpkg -l | grep -q build-essential; then
    echo "build-essential: INSTALLED"
else
    echo "build-essential: NOT INSTALLED"
fi
echo ""

echo "=== Network Ports ==="
echo "Checking common ports used by the project:"
for port in 8931 3000 5000 8080; do
    if sudo netstat -tlnp 2>/dev/null | grep -q ":$port "; then
        echo "Port $port: IN USE"
    else
        echo "Port $port: AVAILABLE"
    fi
done
echo ""

echo "=== Display/GUI Support ==="
if [ -n "$DISPLAY" ]; then
    echo "DISPLAY: $DISPLAY"
else
    echo "DISPLAY: NOT SET"
fi

if [ -n "$WAYLAND_DISPLAY" ]; then
    echo "WAYLAND_DISPLAY: $WAYLAND_DISPLAY"
else
    echo "WAYLAND_DISPLAY: NOT SET"
fi

if [ -d "/tmp/.X11-unix" ]; then
    echo "X11 socket directory: EXISTS"
else
    echo "X11 socket directory: NOT FOUND"
fi
echo ""

echo "=== Disk Space ==="
df -h / | tail -n1 | awk '{print "Root partition: " $4 " available (" $5 " used)"}'
echo ""

echo "=== Memory ==="
free -h | grep "^Mem:" | awk '{print "Total: " $2 ", Available: " $7}'
echo ""

echo "=== End of Diagnostic Report ==="