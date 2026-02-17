#!/bin/bash

# Configuration
INSTALL_DIR="/home/pi/voron_monitor"
SCRIPT_NAME="voron_monitor.py"
SERVICE_NAME="voron_monitor.service"

echo "--- Voron Monitor Installer ---"

# 1. Install Dependencies
echo "[*] Installing dependencies..."
sudo apt-get update
sudo apt-get install -y python3-psutil rt-tests python3-pip

# 2. setup directory
echo "[*] Setting up directory at $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_NAME" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/$SCRIPT_NAME"

# 3. Create Service
echo "[*] Creating systemd service..."
sudo bash -c "cat > /etc/systemd/system/$SERVICE_NAME" <<EOF
[Unit]
Description=Voron Health Monitor
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/$SCRIPT_NAME --log-dir $INSTALL_DIR/logs
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 4. Enable and Start
echo "[*] Enabling and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
sudo systemctl restart $SERVICE_NAME

echo "--- Installation Complete ---"
echo "Monitor is running. Logs are in $INSTALL_DIR/logs"
echo "Check status with: sudo systemctl status $SERVICE_NAME"
