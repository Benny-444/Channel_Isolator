#!/bin/bash

# Channel Isolator - MiniBolt Configuration Script

set -e

echo "Configuring Channel Isolator for MiniBolt..."

# MiniBolt specific paths
LND_DIR="/data/lnd"
BITCOIN_NETWORK="mainnet"
MACAROON_PATH="$LND_DIR/data/chain/bitcoin/$BITCOIN_NETWORK/admin.macaroon"
TLS_CERT_PATH="$LND_DIR/tls.cert"

# Check if running as admin user (minibolt standard)
if [ "$USER" != "admin" ]; then
    echo "Warning: Not running as 'admin' user. MiniBolt typically uses the 'admin' user."
    echo "Current user: $USER"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Verify LND paths exist
if [ ! -f "$MACAROON_PATH" ]; then
    echo "Error: Admin macaroon not found at $MACAROON_PATH"
    echo "Is LND running and fully synced?"
    exit 1
fi

if [ ! -f "$TLS_CERT_PATH" ]; then
    echo "Error: TLS certificate not found at $TLS_CERT_PATH"
    exit 1
fi

# Verify read permissions
if [ ! -r "$MACAROON_PATH" ]; then
    echo "Error: Cannot read admin macaroon. Check permissions."
    echo "You may need to add your user to the 'lnd' group:"
    echo "  sudo usermod -a -G lnd $USER"
    echo "Then log out and back in."
    exit 1
fi

# Create MiniBolt-specific wrapper script
INSTALL_DIR="$HOME/channel_isolator"
mkdir -p "$INSTALL_DIR"

cat > "$INSTALL_DIR/channel-isolator-minibolt" << EOF
#!/bin/bash
# MiniBolt-configured Channel Isolator wrapper
DIR="\$( cd "\$( dirname "\${BASH_SOURCE[0]}" )" && pwd )"
source "\$DIR/venv/bin/activate"
python "\$DIR/channel_isolator.py" --lnd-dir "$LND_DIR" --network "$BITCOIN_NETWORK" "\$@"
EOF

chmod +x "$INSTALL_DIR/channel-isolator-minibolt"

# Create systemd service file for MiniBolt
cat > "$INSTALL_DIR/channel-isolator-minibolt.service" << EOF
[Unit]
Description=Channel Isolator - LND HTLC Interceptor (MiniBolt)
After=lnd.service
Requires=lnd.service
PartOf=lnd.service

[Service]
Type=simple
ExecStartPre=/bin/sleep 10
ExecStart=$INSTALL_DIR/channel-isolator-minibolt
Restart=always
RestartSec=30
User=$USER
Group=$USER

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_DIR
ReadOnlyPaths=$LND_DIR/tls.cert $LND_DIR/data/chain/bitcoin/$BITCOIN_NETWORK/admin.macaroon

# Logging
StandardOutput=journal
StandardError=journal

# Environment
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

# Create a custom macaroon with only required permissions (optional but more secure)
echo ""
echo "For enhanced security, you can create a custom macaroon with limited permissions."
echo "This is optional - the admin macaroon will work fine."
echo ""
read -p "Create custom macaroon? (y/n) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Creating custom macaroon with required permissions..."
    
    # Check if lncli is available
    if ! command -v lncli &> /dev/null; then
        echo "Error: lncli not found in PATH"
        exit 1
    fi
    
    # Create macaroon with only necessary permissions
    lncli bakemacaroon \
        info:read \
        onchain:read \
        offchain:read \
        address:read \
        message:read \
        peers:read \
        signer:read \
        macaroon:read \
        router:read \
        router:write > "$INSTALL_DIR/channel_isolator.macaroon.hex"
    
    # Convert hex to binary
    xxd -r -p "$INSTALL_DIR/channel_isolator.macaroon.hex" > "$INSTALL_DIR/channel_isolator.macaroon"
    rm "$INSTALL_DIR/channel_isolator.macaroon.hex"
    
    # Update wrapper to use custom macaroon
    cat > "$INSTALL_DIR/channel-isolator-custom" << EOF
#!/bin/bash
# MiniBolt Channel Isolator with custom macaroon
DIR="\$( cd "\$( dirname "\${BASH_SOURCE[0]}" )" && pwd )"
source "\$DIR/venv/bin/activate"

# Create temporary directory for custom LND config
TEMP_LND_DIR=\$(mktemp -d)
mkdir -p "\$TEMP_LND_DIR/data/chain/bitcoin/$BITCOIN_NETWORK"

# Copy TLS cert and custom macaroon
cp "$TLS_CERT_PATH" "\$TEMP_LND_DIR/tls.cert"
cp "\$DIR/channel_isolator.macaroon" "\$TEMP_LND_DIR/data/chain/bitcoin/$BITCOIN_NETWORK/admin.macaroon"

# Run with custom paths
python "\$DIR/channel_isolator.py" --lnd-dir "\$TEMP_LND_DIR" --network "$BITCOIN_NETWORK" "\$@"

# Cleanup
rm -rf "\$TEMP_LND_DIR"
EOF
    
    chmod +x "$INSTALL_DIR/channel-isolator-custom"
    chmod 600 "$INSTALL_DIR/channel_isolator.macaroon"
    
    echo "Custom macaroon created successfully!"
    echo "Use: $INSTALL_DIR/channel-isolator-custom"
else
    echo "Skipping custom macaroon creation."
fi

echo ""
echo "MiniBolt configuration complete!"
echo ""
echo "Installation summary:"
echo "  - LND directory: $LND_DIR"
echo "  - Network: $BITCOIN_NETWORK"
echo "  - Service user: $USER"
echo ""
echo "To complete installation:"
echo "  1. Install as systemd service:"
echo "     sudo cp $INSTALL_DIR/channel-isolator-minibolt.service /etc/systemd/system/channel-isolator.service"
echo "     sudo systemctl daemon-reload"
echo "     sudo systemctl enable channel-isolator"
echo "     sudo systemctl start channel-isolator"
echo ""
echo "  2. Check service status:"
echo "     sudo systemctl status channel-isolator"
echo "     sudo journalctl -u channel-isolator -f"
echo ""
echo "Security notes:"
echo "  - Running as user: $USER (has access to LND files)"
echo "  - Service includes security hardening options"
echo "  - Consider using custom macaroon for production"
echo ""
echo "If you encounter permission issues, ensure your user is in the 'lnd' group:"
echo "  sudo usermod -a -G lnd $USER"
echo "  (then log out and back in)"
