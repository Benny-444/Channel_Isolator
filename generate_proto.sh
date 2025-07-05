#!/bin/bash

# Channel Isolator - Dynamic Proto File Generation Script
# Usage: ./generate_proto.sh [lnd_version]
#   - If lnd_version is provided (e.g., v0.19.0-beta), fetches proto files for that version.
#   - If not provided, defaults to the master branch.

set -e

echo "Generating LND proto files..."

INSTALL_DIR="$HOME/channel_isolator"
cd "$INSTALL_DIR"

# Check for virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

# Install dependencies if needed
if ! python -c "import grpc_tools" 2>/dev/null; then
    echo "Installing dependencies..."
    pip install --upgrade pip
    pip install grpcio-tools==1.62.2
fi

mkdir -p proto

# Use provided LND version or default to master
LND_VERSION="${1:-master}"
echo "Using LND version: $LND_VERSION"

# Set proto file URLs based on version
if [ "$LND_VERSION" == "master" ]; then
    PROTO_URL="https://raw.githubusercontent.com/lightningnetwork/lnd/master/lnrpc/lightning.proto"
    ROUTER_PROTO_URL="https://raw.githubusercontent.com/lightningnetwork/lnd/master/lnrpc/routerrpc/router.proto"
else
    PROTO_URL="https://raw.githubusercontent.com/lightningnetwork/lnd/$LND_VERSION/lnrpc/lightning.proto"
    ROUTER_PROTO_URL="https://raw.githubusercontent.com/lightningnetwork/lnd/$LND_VERSION/lnrpc/routerrpc/router.proto"
fi

# Download proto files
echo "Downloading proto files..."
wget -q -O proto/lightning.proto "$PROTO_URL" || { echo "Error: Failed to download lightning.proto for version $LND_VERSION"; exit 1; }
wget -q -O proto/router.proto "$ROUTER_PROTO_URL" || { echo "Error: Failed to download router.proto for version $LND_VERSION"; exit 1; }

# Generate Python files
echo "Generating Python gRPC files..."
python -m grpc_tools.protoc -Iproto --python_out=. --grpc_python_out=. proto/lightning.proto
python -m grpc_tools.protoc -Iproto --python_out=. --grpc_python_out=. proto/router.proto

# Verify generation
if [ -f "lightning_pb2.py" ] && [ -f "lightning_pb2_grpc.py" ] && [ -f "router_pb2.py" ] && [ -f "router_pb2_grpc.py" ]; then
    echo "Proto files generated successfully!"
else
    echo "Error: Failed to generate proto files"
    exit 1
fi