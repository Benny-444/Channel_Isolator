#!/bin/bash

# Channel Isolator Installation Script
# For MiniBolt on Ubuntu 22.04

set -e

echo "Channel Isolator Installer"
echo "========================="
echo ""

# Configuration
INSTALL_DIR="$HOME/channel_isolator"
SERVICE_FILE="/etc/systemd/system/channel-isolator.service"

# Create installation directory
echo "Creating installation directory..."
mkdir -p "$INSTALL_DIR"

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

# Check if pip is installed
if ! command -v pip3 &> /dev/null; then
    echo "Error: pip3 is required but not installed."
    exit 1
fi

# Copy scripts to installation directory
echo "Copying files to $INSTALL_DIR..."

# Note: This script assumes the files are in the current directory
if [ ! -f "channel_isolator.py" ]; then
    echo "Error: channel_isolator.py not found in current directory"
    exit 1
fi

cp channel_isolator.py "$INSTALL_DIR/"
cp channel_isolator_cli.py "$INSTALL_DIR/"
cp requirements.txt "$INSTALL_DIR/"
cp generate_proto.sh "$INSTALL_DIR/"

# Make scripts executable
chmod +x "$INSTALL_DIR/channel_isolator.py"
chmod +x "$INSTALL_DIR/channel_isolator_cli.py"
chmod +x "$INSTALL_DIR/generate_proto.sh"

# Set proper permissions
chmod 700 "$INSTALL_DIR"
chmod 600 "$INSTALL_DIR/channel_isolator.py"
chmod 600 "$INSTALL_DIR/channel_isolator_cli.py"

# Create virtual environment
echo "Creating virtual environment..."
cd "$INSTALL_DIR"
python3 -m venv venv

# Activate virtual environment and install dependencies
echo "Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Generate proto files
echo "Generating LND proto files..."
./generate_proto.sh

# Create wrapper scripts that use the virtual environment
echo "Creating wrapper scripts..."

# Main service wrapper
cat > "$INSTALL_DIR/channel-isolator" << 'EOF'
#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$DIR/venv/bin/activate"
python "$DIR/channel_isolator.py" "$@"
EOF

# CLI wrapper
cat > "$INSTALL_DIR/channel-isolator-cli" << 'EOF'
#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$DIR/venv/bin/activate"
python "$DIR/channel_isolator_cli.py" "$@"
EOF

chmod +x "$INSTALL_DIR/channel-isolator"
chmod +x "$INSTALL_DIR/channel-isolator-cli"

# Create systemd service file (optional)
echo "Creating systemd service file template..."
cat > "$INSTALL_DIR/channel-isolator.service" << EOF
[Unit]
Description=Channel Isolator - LND HTLC Interceptor
After=lnd.service
Requires=lnd.service
PartOf=lnd.service

[Service]
Type=simple
ExecStartPre=/bin/sleep 10
ExecStart=$INSTALL_DIR/channel-isolator
Restart=always
RestartSec=30
User=$USER
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo ""
echo "Installation complete!"
echo ""
echo "To use Channel Isolator:"
echo "  1. Start the service: $INSTALL_DIR/channel-isolator"
echo "  2. Use the CLI tool: $INSTALL_DIR/channel-isolator-cli"
echo ""
echo "Example commands:"
echo "  - Isolate a channel: $INSTALL_DIR/channel-isolator-cli isolate <channel_id>"
echo "  - Add exception: $INSTALL_DIR/channel-isolator-cli add-exception <isolated_channel> <allowed_channel>"
echo "  - List isolated channels: $INSTALL_DIR/channel-isolator-cli list"
echo "  - Show statistics: $INSTALL_DIR/channel-isolator-cli stats"
echo ""
echo "To install as a systemd service (optional):"
echo "  sudo cp $INSTALL_DIR/channel-isolator.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable channel-isolator"
echo "  sudo systemctl start channel-isolator"
echo ""
echo "For MiniBolt users, run the MiniBolt configuration script:"
echo "  cd $INSTALL_DIR"
echo "  ./minibolt_config.sh"
echo ""
echo "Add to PATH for easier access:"
echo "  echo 'export PATH=\"\$PATH:$INSTALL_DIR\"' >> ~/.bashrc"
echo "  source ~/.bashrc"
