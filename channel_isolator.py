#!/usr/bin/env python3
"""
Channel Isolator - LND HTLC Interceptor
Blocks incoming HTLCs to specific channels except from allowed sources
"""

import os
import sys
import grpc
import sqlite3
import logging
import signal
import codecs
import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import Set, Optional, Dict
from queue import Queue, Empty
from threading import Thread, Event, Lock

# Set required gRPC environment variable
os.environ["GRPC_SSL_CIPHER_SUITES"] = 'HIGH+ECDSA'

# Import generated proto files
try:
    import lightning_pb2 as ln
    import lightning_pb2_grpc as lnrpc
    import router_pb2 as routerrpc
    import router_pb2_grpc as routerstub
except ImportError:
    print("Error: Proto files not found. Please run generate_proto.sh first.")
    sys.exit(1)

# Configuration paths
HOME = Path.home()
INSTALL_DIR = HOME / "channel_isolator"
DB_PATH = INSTALL_DIR / "channel_isolator.db"
CONFIG_PATH = INSTALL_DIR / "config.json"
LOG_PATH = INSTALL_DIR / "channel_isolator.log"

# Default LND paths - MiniBolt standard
DEFAULT_LND_DIR = Path("/data/lnd")
DEFAULT_MACAROON = DEFAULT_LND_DIR / "data/chain/bitcoin/mainnet/admin.macaroon"
DEFAULT_TLS_CERT = DEFAULT_LND_DIR / "tls.cert"

class ChannelIsolator:
    def __init__(self, lnd_dir: Path, network: str = "mainnet"):
        self.lnd_dir = Path(lnd_dir)
        self.network = network
        self.macaroon_path = self.lnd_dir / f"data/chain/bitcoin/{network}/admin.macaroon"
        self.tls_cert_path = self.lnd_dir / "tls.cert"
        self.db_conn = None
        self.stub = None
        self.router_stub = None
        self.active_sessions: Dict[str, int] = {}  # channel_id -> session_id
        self.exception_lists: Dict[str, Set[str]] = {}  # channel_id -> set of allowed channels
        self.running = False
        self.shutdown_event = Event()

        # Add synchronization attributes
        self.last_db_check_time = 0
        self.db_check_interval = 0.5  # Check every 500ms max
        self.sessions_lock = Lock()
        self.last_db_modified = 0

        # Setup logging
        self.setup_logging()

        # Initialize database
        self.init_database()

        # Load active sessions
        self.load_active_sessions()

        # Set initial DB modified time
        self.last_db_modified = self.get_db_last_modified()

    def setup_logging(self):
        """Configure logging to file and console"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(LOG_PATH),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger('ChannelIsolator')

    def init_database(self):
        """Initialize SQLite database with required tables"""
        # Use check_same_thread=False for thread safety
        self.db_conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        cursor = self.db_conn.cursor()

        # Create isolation sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS isolation_sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                channel_alias TEXT,
                start_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                end_timestamp DATETIME,
                status TEXT DEFAULT 'active',
                total_attempts INTEGER DEFAULT 0,
                total_allowed INTEGER DEFAULT 0,
                total_rejected INTEGER DEFAULT 0
            )
        ''')

        # Create HTLC attempts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS htlc_attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                source_channel_id TEXT NOT NULL,
                source_alias TEXT,
                amount_msat INTEGER,
                decision TEXT NOT NULL,
                outcome TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES isolation_sessions(session_id)
            )
        ''')

        # Create exception list table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS exception_list (
                exception_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                allowed_channel_id TEXT NOT NULL,
                allowed_alias TEXT,
                added_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES isolation_sessions(session_id)
            )
        ''')

        # Create metadata table for tracking DB changes
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS db_metadata (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Initialize last_modified if not exists
        cursor.execute('''
            INSERT OR IGNORE INTO db_metadata (key, value) VALUES ('last_modified', datetime('now'))
        ''')

        self.db_conn.commit()
        self.logger.info("Database initialized successfully")

    def get_db_last_modified(self):
        """Get the last modification timestamp from database"""
        cursor = self.db_conn.cursor()
        cursor.execute("SELECT value FROM db_metadata WHERE key = 'last_modified'")
        result = cursor.fetchone()
        if result:
            return datetime.fromisoformat(result[0]).timestamp()
        return 0

    def check_and_reload_sessions(self):
        """Check if database has been modified and reload if necessary"""
        current_time = time.time()

        # Rate limit checks to avoid excessive DB queries
        if current_time - self.last_db_check_time < self.db_check_interval:
            return

        self.last_db_check_time = current_time

        # Check if DB has been modified
        db_modified = self.get_db_last_modified()

        if db_modified > self.last_db_modified:
            self.logger.info("Database modification detected, reloading sessions...")
            self.load_active_sessions()
            self.last_db_modified = db_modified

    def connect_to_lnd(self):
        """Establish gRPC connection to LND"""
        try:
            # Load credentials
            self.logger.info("Reading LND credentials...")
            with open(self.tls_cert_path, 'rb') as f:
                cert = f.read()

            with open(self.macaroon_path, 'rb') as f:
                macaroon = codecs.encode(f.read(), 'hex')

            self.logger.info("Credentials loaded successfully")

            # Set up gRPC channel
            def metadata_callback(context, callback):
                callback([('macaroon', macaroon)], None)

            auth_creds = grpc.metadata_call_credentials(metadata_callback)
            cert_creds = grpc.ssl_channel_credentials(cert)
            combined_creds = grpc.composite_channel_credentials(cert_creds, auth_creds)

            self.logger.info("Attempting to connect to LND...")
            channel = grpc.secure_channel('localhost:10009', combined_creds)

            # Create stubs
            self.stub = lnrpc.LightningStub(channel)
            self.router_stub = routerstub.RouterStub(channel)

            # Test connection
            request = ln.GetInfoRequest()
            response = self.stub.GetInfo(request)
            self.logger.info(f"Connected to LND node: {response.alias} ({response.identity_pubkey})")

            return True

        except Exception as e:
            self.logger.error(f"Failed to connect to LND: {e}")
            return False

    def load_active_sessions(self):
        """Load active isolation sessions from database"""
        with self.sessions_lock:
            cursor = self.db_conn.cursor()
            cursor.execute('''
                SELECT session_id, channel_id FROM isolation_sessions
                WHERE status = 'active'
            ''')

            # Clear existing sessions
            self.active_sessions.clear()
            self.exception_lists.clear()

            for session_id, channel_id in cursor.fetchall():
                self.active_sessions[channel_id] = session_id
                self.exception_lists[channel_id] = set()

                # Load exceptions for this session
                cursor.execute('''
                    SELECT allowed_channel_id FROM exception_list
                    WHERE session_id = ?
                ''', (session_id,))

                for (allowed_channel,) in cursor.fetchall():
                    self.exception_lists[channel_id].add(allowed_channel)

            self.logger.info(f"Loaded {len(self.active_sessions)} active isolation sessions")

    def update_db_timestamp(self):
        """Update the last_modified timestamp in database"""
        cursor = self.db_conn.cursor()
        cursor.execute('''
            UPDATE db_metadata SET value = datetime('now'), updated_at = datetime('now')
            WHERE key = 'last_modified'
        ''')
        self.db_conn.commit()

    def start_isolation(self, channel_id: str, channel_alias: str = None) -> int:
        """Start isolating a channel"""
        if channel_id in self.active_sessions:
            self.logger.warning(f"Channel {channel_id} is already isolated")
            return self.active_sessions[channel_id]

        cursor = self.db_conn.cursor()
        cursor.execute('''
            INSERT INTO isolation_sessions (channel_id, channel_alias)
            VALUES (?, ?)
        ''', (channel_id, channel_alias))

        session_id = cursor.lastrowid

        # Update timestamp to trigger reload in service
        self.update_db_timestamp()
        self.db_conn.commit()

        self.active_sessions[channel_id] = session_id
        self.exception_lists[channel_id] = set()

        self.logger.info(f"Started isolation session {session_id} for channel {channel_id}")
        return session_id

    def stop_isolation(self, channel_id: str):
        """Stop isolating a channel"""
        if channel_id not in self.active_sessions:
            self.logger.warning(f"Channel {channel_id} is not currently isolated")
            return

        session_id = self.active_sessions[channel_id]

        cursor = self.db_conn.cursor()
        cursor.execute('''
            UPDATE isolation_sessions
            SET end_timestamp = CURRENT_TIMESTAMP, status = 'completed'
            WHERE session_id = ?
        ''', (session_id,))

        # Update timestamp to trigger reload in service
        self.update_db_timestamp()
        self.db_conn.commit()

        del self.active_sessions[channel_id]
        del self.exception_lists[channel_id]

        self.logger.info(f"Stopped isolation session {session_id} for channel {channel_id}")

    def add_exception(self, channel_id: str, allowed_channel: str, allowed_alias: str = None):
        """Add a channel to the exception list"""
        if channel_id not in self.active_sessions:
            self.logger.error(f"Channel {channel_id} is not isolated")
            return

        session_id = self.active_sessions[channel_id]
        self.exception_lists[channel_id].add(allowed_channel)

        cursor = self.db_conn.cursor()
        cursor.execute('''
            INSERT INTO exception_list (session_id, allowed_channel_id, allowed_alias)
            VALUES (?, ?, ?)
        ''', (session_id, allowed_channel, allowed_alias))

        # Update timestamp to trigger reload in service
        self.update_db_timestamp()
        self.db_conn.commit()

        self.logger.info(f"Added exception: {allowed_channel} can route to {channel_id}")

    def remove_exception(self, channel_id: str, allowed_channel: str):
        """Remove a channel from the exception list"""
        if channel_id not in self.active_sessions:
            self.logger.error(f"Channel {channel_id} is not isolated")
            return

        session_id = self.active_sessions[channel_id]

        cursor = self.db_conn.cursor()
        cursor.execute('''
            DELETE FROM exception_list WHERE session_id = ? AND allowed_channel_id = ?
        ''', (session_id, allowed_channel))

        # Update timestamp to trigger reload in service
        self.update_db_timestamp()
        self.db_conn.commit()

        if allowed_channel in self.exception_lists[channel_id]:
            self.exception_lists[channel_id].remove(allowed_channel)
            self.logger.info(f"Removed exception: {allowed_channel} from {channel_id}")

    def log_htlc_attempt(self, session_id: int, source_channel: str, amount_msat: int,
                        decision: str, outcome: str = None, source_alias: str = None):
        """Log an HTLC attempt to the database"""
        cursor = self.db_conn.cursor()

        # Insert the attempt
        cursor.execute('''
            INSERT INTO htlc_attempts
            (session_id, source_channel_id, source_alias, amount_msat, decision, outcome)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (session_id, source_channel, source_alias, amount_msat, decision, outcome))

        # Update session statistics
        if decision == 'allowed':
            cursor.execute('''
                UPDATE isolation_sessions
                SET total_attempts = total_attempts + 1,
                    total_allowed = total_allowed + 1
                WHERE session_id = ?
            ''', (session_id,))
        else:  # rejected
            cursor.execute('''
                UPDATE isolation_sessions
                SET total_attempts = total_attempts + 1,
                    total_rejected = total_rejected + 1
                WHERE session_id = ?
            ''', (session_id,))

        self.db_conn.commit()

    def intercept_htlcs(self):
        """Main HTLC interception loop using bidirectional streaming with queue"""
        if not self.router_stub:
            self.logger.error("Not connected to LND")
            return

        self.logger.info("Starting HTLC interception...")
        response_queue = Queue()

        def response_generator():
            """Generator that yields responses from the queue"""
            while not self.shutdown_event.is_set():
                try:
                    response = response_queue.get(timeout=1)
                    if response is None:  # Shutdown signal
                        return
                    yield response
                except Empty:
                    continue

        # Create bidirectional stream
        htlc_stream = self.router_stub.HtlcInterceptor(response_generator())

        def process_htlcs():
            """Process incoming HTLCs and queue responses"""
            try:
                for htlc in htlc_stream:
                    if self.shutdown_event.is_set():
                        break

                    # Check for database changes before processing each HTLC
                    self.check_and_reload_sessions()

                    # Get channel IDs
                    incoming_channel = str(htlc.incoming_circuit_key.chan_id)
                    outgoing_channel = str(htlc.outgoing_requested_chan_id)
                    amount_msat = htlc.outgoing_amount_msat

                    # Default action is to resume (allow)
                    action = routerrpc.ResolveHoldForwardAction.RESUME
                    decision = 'allowed'

                    # Check if outgoing channel is isolated (with thread safety)
                    with self.sessions_lock:
                        if outgoing_channel in self.active_sessions:
                            session_id = self.active_sessions[outgoing_channel]

                            # Check if incoming channel is in exception list
                            if incoming_channel not in self.exception_lists[outgoing_channel]:
                                # Block this HTLC
                                action = routerrpc.ResolveHoldForwardAction.FAIL
                                decision = 'rejected'
                                self.logger.info(
                                    f"Blocked HTLC: {incoming_channel} -> {outgoing_channel} "
                                    f"(amount: {amount_msat} msat)"
                                )
                            else:
                                self.logger.info(
                                    f"Allowed HTLC: {incoming_channel} -> {outgoing_channel} "
                                    f"(amount: {amount_msat} msat)"
                                )

                            # Log the attempt
                            self.log_htlc_attempt(
                                session_id,
                                incoming_channel,
                                amount_msat,
                                decision
                            )

                    # Queue the response
                    response = routerrpc.ForwardHtlcInterceptResponse(
                        incoming_circuit_key=htlc.incoming_circuit_key,
                        action=action
                    )
                    response_queue.put(response)

            except grpc.RpcError as e:
                if e.code() != grpc.StatusCode.CANCELLED:
                    self.logger.error(f"gRPC error in HTLC interceptor: {e}")
            except Exception as e:
                self.logger.error(f"Error processing HTLC: {e}")
            finally:
                # Signal shutdown
                response_queue.put(None)

        # Start processing thread
        thread = Thread(target=process_htlcs)
        thread.start()

        # Wait for thread to complete or shutdown event
        while not self.shutdown_event.is_set():
            thread.join(timeout=1)
            if not thread.is_alive():
                break

        # Ensure thread completes
        if thread.is_alive():
            response_queue.put(None)
            thread.join(timeout=5)

    def run(self):
        """Main run loop"""
        self.logger.info("Starting Channel Isolator...")

        if not self.connect_to_lnd():
            self.logger.error("Failed to connect to LND. Exiting.")
            return

        self.running = True

        # Set up signal handlers
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)

        self.logger.info("Channel Isolator is running. Press Ctrl+C to stop.")

        # Run the interceptor with reconnection logic
        while self.running and not self.shutdown_event.is_set():
            try:
                self.intercept_htlcs()
            except Exception as e:
                if self.running and not self.shutdown_event.is_set():
                    self.logger.error(f"Interceptor error: {e}. Reconnecting in 5 seconds...")
                    time.sleep(5)
                    # Try to reconnect
                    if not self.connect_to_lnd():
                        self.logger.error("Reconnection failed. Retrying in 30 seconds...")
                        time.sleep(30)

    def shutdown(self, signum=None, frame=None):
        """Graceful shutdown"""
        self.logger.info("Shutting down Channel Isolator...")
        self.running = False
        self.shutdown_event.set()

        if self.db_conn:
            self.db_conn.close()

        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description='Channel Isolator - LND HTLC Interceptor')
    parser.add_argument('--lnd-dir', type=str, default=str(DEFAULT_LND_DIR),
                       help='Path to LND directory')
    parser.add_argument('--network', type=str, default='mainnet',
                       help='Bitcoin network (mainnet/testnet/regtest)')

    args = parser.parse_args()

    # Ensure install directory exists
    INSTALL_DIR.mkdir(exist_ok=True)

    # Create and run isolator
    isolator = ChannelIsolator(args.lnd_dir, args.network)
    isolator.run()


if __name__ == "__main__":
    main()