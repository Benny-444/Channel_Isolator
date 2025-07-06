# Channel Isolator

A Lightning Network tool that uses LND's HTLC interceptor to selectively block incoming HTLCs to specific channels while maintaining an exception list for allowed source channels.

## Overview

Channel Isolator allows you to:
- Block all incoming HTLCs to specific channels (preserving outbound liquidity)
- Maintain an exception list of channels that ARE allowed to route into isolated channels
- Allow all outgoing HTLCs from isolated channels (depleting inbound liquidity)
- Track and analyze routing attempts with detailed logging

## Installation

### Prerequisites
- LND node with admin macaroon access (v0.9.0+)
- Python 3.8 or higher
- pip3 package manager
- Ubuntu 22.04 or compatible Linux distribution

### Quick Install

1. Clone or download the Channel Isolator files to your system
2. Ensure all files are in the same directory
3. Run the installation script:
   ```bash
   chmod +x install.sh
   ./install.sh
   ```

### MiniBolt Installation

For MiniBolt nodes specifically:
1. First run the standard installation
2. Then run the MiniBolt configuration:
   ```bash
   cd ~/channel_isolator
   chmod +x minibolt_config.sh
   ./minibolt_config.sh
   ```

### Manual Installation

1. Create the installation directory:
   ```bash
   mkdir -p ~/channel_isolator
   cd ~/channel_isolator
   ```

2. Copy all Python scripts and requirements file to the directory

3. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. Generate proto files:
   ```bash
   chmod +x generate_proto.sh
   ./generate_proto.sh
   ```

## Usage

### Starting the Service

Run the Channel Isolator service:
```bash
~/channel_isolator/channel-isolator
```

For MiniBolt users:
```bash
~/channel_isolator/channel-isolator-minibolt
```

Options:
- `--lnd-dir`: Path to LND directory (default: /data/lnd)
- `--network`: Bitcoin network - mainnet/testnet/regtest (default: mainnet)

### CLI Commands

The CLI tool (`channel-isolator-cli`) provides the following commands:

#### Isolate a Channel
```bash
~/channel_isolator/channel-isolator-cli isolate <channel_id> [--alias "Channel Name"]
```

#### Stop Isolating a Channel
```bash
~/channel_isolator/channel-isolator-cli stop <channel_id>
```

#### Add Exception (Allow a Channel)
```bash
~/channel_isolator/channel-isolator-cli add-exception <isolated_channel_id> <allowed_channel_id> [--alias "Allowed Channel"]
```

#### Remove Exception
```bash
~/channel_isolator/channel-isolator-cli remove-exception <isolated_channel_id> <allowed_channel_id>
```

#### List Currently Isolated Channels
```bash
~/channel_isolator/channel-isolator-cli list
```

#### Show Exceptions for a Channel
```bash
~/channel_isolator/channel-isolator-cli exceptions <channel_id>
```

#### View Isolation History
```bash
~/channel_isolator/channel-isolator-cli history [--channel <channel_id>]
```

#### View HTLC Attempts for a Session
```bash
~/channel_isolator/channel-isolator-cli attempts <session_id>
```

#### Show Overall Statistics
```bash
~/channel_isolator/channel-isolator-cli stats
```

## Example Workflow

1. Start the Channel Isolator service:
   ```bash
   ~/channel_isolator/channel-isolator &
   ```

2. Isolate a channel to preserve its outbound liquidity:
   ```bash
   ~/channel_isolator/channel-isolator-cli isolate 123456789012345678 --alias "Premium Route"
   ```

3. Add exceptions for your own channels that should be allowed to route through:
   ```bash
   ~/channel_isolator/channel-isolator-cli add-exception 123456789012345678 987654321098765432 --alias "My Other Channel"
   ```

4. Monitor routing attempts:
   ```bash
   ~/channel_isolator/channel-isolator-cli list
   ~/channel_isolator/channel-isolator-cli attempts 1
   ```

5. When done, stop the isolation:
   ```bash
   ~/channel_isolator/channel-isolator-cli stop 123456789012345678
   ```

## Database Schema

The tool uses SQLite to maintain state and log all routing attempts:

- **isolation_sessions**: Tracks isolation periods for channels
- **htlc_attempts**: Logs all HTLC intercept decisions
- **exception_list**: Stores allowed channels for each isolation session

Database location: `~/channel_isolator/channel_isolator.db`

## Running as a Service

To run Channel Isolator as a systemd service:

1. Copy the service file:
   ```bash
   sudo cp ~/channel_isolator/channel-isolator.service /etc/systemd/system/
   ```
   
   For MiniBolt:
   ```bash
   sudo cp ~/channel_isolator/channel-isolator-minibolt.service /etc/systemd/system/channel-isolator.service
   ```

2. Enable and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable channel-isolator
   sudo systemctl start channel-isolator
   ```

3. Check service status:
   ```bash
   sudo systemctl status channel-isolator
   ```

4. View logs:
   ```bash
   sudo journalctl -u channel-isolator -f
   ```

## MiniBolt Specific Notes

MiniBolt users should be aware of these specifics:
- Default LND directory is `/data/lnd`
- Service runs as the `admin` user by default
- Enhanced security hardening is applied in the systemd service
- Custom macaroon creation is available for improved security

If you encounter permission issues:
```bash
sudo usermod -a -G lnd $USER
# Then log out and back in
```

## Important Notes

- The Channel Isolator must be running for isolation rules to be enforced
- All outgoing HTLCs are always allowed (isolation only affects incoming HTLCs)
- Each isolation period is tracked as a separate session in the database
- The tool requires admin macaroon access to intercept HTLCs
- The service automatically reconnects if the connection to LND is lost

## Limitations
- Only one HTLC interceptor can run at a time in LND (v0.19.1 at the time of writing this document). If you're using CircuitBreaker or another interceptor, you cannot run Channel Isolator simultaneously

## Troubleshooting

1. **Connection Issues**: 
   - Ensure LND is running and the paths to tls.cert and admin.macaroon are correct
   - Check that the specified network matches your LND configuration

2. **Permission Errors**: 
   - Make sure your user has read access to LND's tls.cert and admin.macaroon files
   - For MiniBolt, ensure you're part of the `lnd` group

3. **Database Errors**: 
   - Check that ~/channel_isolator/ directory exists and is writable
   - Ensure the service has write permissions to create log files

4. **Service Won't Start**:
   - Check logs with `sudo journalctl -u channel-isolator -n 50`
   - Verify LND is running: `sudo systemctl status lnd`
   - Ensure Python virtual environment was created successfully

## Security Considerations

- The admin.macaroon provides full access to your LND node - keep it secure
- The database contains routing information - protect it appropriately
- Consider running with a custom macaroon (MiniBolt users can create one during setup)
- The systemd service includes security hardening options for MiniBolt

## Files Included

- `channel_isolator.py` - Main service script
- `channel_isolator_cli.py` - Command-line interface
- `install.sh` - Installation script
- `generate_proto.sh` - Proto file generator
- `minibolt_config.sh` - MiniBolt-specific configuration
- `requirements.txt` - Python dependencies
- `README.md` - This file

## License

This project is released under the MIT License.