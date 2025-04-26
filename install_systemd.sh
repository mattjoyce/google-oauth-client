#!/bin/bash
# Script to install the Google OAuth Client systemd service and timer

# Ensure script is run as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (use sudo)"
  exit 1
fi

# Get the current directory (where the script is located)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Get the current user (the one who ran sudo)
CURRENT_USER=$(logname || echo "$SUDO_USER")
if [ -z "$CURRENT_USER" ]; then
  echo "Could not determine the current user. Please edit the service file manually."
  CURRENT_USER="YOUR_USERNAME"
fi

# Check if service and timer files exist
SERVICE_FILE="${SCRIPT_DIR}/google-oauth-refresh.service"
TIMER_FILE="${SCRIPT_DIR}/google-oauth-refresh.timer"

if [ ! -f "$SERVICE_FILE" ]; then
  echo "Error: ${SERVICE_FILE} not found"
  exit 1
fi

if [ ! -f "$TIMER_FILE" ]; then
  echo "Error: ${TIMER_FILE} not found"
  exit 1
fi

# Replace placeholders in the service file
sed "s|/path/to/google-oauth-client|${SCRIPT_DIR}|g; s|YOUR_USERNAME|${CURRENT_USER}|g" "$SERVICE_FILE" > /etc/systemd/system/google-oauth-refresh.service

# Copy the timer file (no replacements needed)
cp "$TIMER_FILE" /etc/systemd/system/google-oauth-refresh.timer

# Reload systemd configuration
systemctl daemon-reload

# Enable and start the timer
systemctl enable google-oauth-refresh.timer
systemctl start google-oauth-refresh.timer

# Verify status
echo "Service and timer installed successfully!"
echo "Timer status:"
systemctl status google-oauth-refresh.timer

echo ""
echo "To manually run the service once, use:"
echo "sudo systemctl start google-oauth-refresh.service"
echo ""
echo "To view logs, use:"
echo "journalctl -u google-oauth-refresh.service"
