#!/usr/bin/env python3
"""
Channel Isolator CLI - Management tool for Channel Isolator
"""

import os
import sys
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime
from tabulate import tabulate

# Configuration paths
HOME = Path.home()
INSTALL_DIR = HOME / "channel_isolator"
DB_PATH = INSTALL_DIR / "channel_isolator.db"

class ChannelIsolatorCLI:
    def __init__(self):
        self.db_path = DB_PATH
        if not self.db_path.exists():
            print(f"Database not found at {self.db_path}")
            print("Please run the Channel Isolator service first to initialize the database.")
            sys.exit(1)

    def execute_query(self, query, params=None):
        """Execute a query and return results"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        results = cursor.fetchall()
        conn.commit()
        conn.close()

        return results

    def isolate_channel(self, channel_id, alias=None):
        """Start isolating a channel"""
        # Check if already isolated
        results = self.execute_query(
            "SELECT session_id FROM isolation_sessions WHERE channel_id = ? AND status = 'active'",
            (channel_id,)
        )

        if results:
            print(f"Channel {channel_id} is already isolated (session {results[0][0]})")
            return

        # Create new isolation session
        self.execute_query(
            "INSERT INTO isolation_sessions (channel_id, channel_alias) VALUES (?, ?)",
            (channel_id, alias)
        )
        self.execute_query("UPDATE db_metadata SET value = datetime('now'), updated_at = datetime('now') WHERE key = 'last_modified'")

        print(f"Started isolating channel {channel_id}")
        if alias:
            print(f"Alias: {alias}")

    def stop_isolation(self, channel_id):
        """Stop isolating a channel"""
        results = self.execute_query(
            "SELECT session_id FROM isolation_sessions WHERE channel_id = ? AND status = 'active'",
            (channel_id,)
        )

        if not results:
            print(f"Channel {channel_id} is not currently isolated")
            return

        session_id = results[0][0]
        self.execute_query(
            "UPDATE isolation_sessions SET end_timestamp = CURRENT_TIMESTAMP, status = 'completed' WHERE session_id = ?",
            (session_id,)
        )
        self.execute_query("UPDATE db_metadata SET value = datetime('now'), updated_at = datetime('now') WHERE key = 'last_modified'")

        print(f"Stopped isolating channel {channel_id} (session {session_id})")

    def add_exception(self, isolated_channel, allowed_channel, alias=None):
        """Add an exception for a channel"""
        # Get active session
        results = self.execute_query(
            "SELECT session_id FROM isolation_sessions WHERE channel_id = ? AND status = 'active'",
            (isolated_channel,)
        )

        if not results:
            print(f"Channel {isolated_channel} is not currently isolated")
            return

        session_id = results[0][0]

        # Check if exception already exists
        existing = self.execute_query(
            "SELECT exception_id FROM exception_list WHERE session_id = ? AND allowed_channel_id = ?",
            (session_id, allowed_channel)
        )

        if existing:
            print(f"Exception already exists for channel {allowed_channel}")
            return

        # Add exception
        self.execute_query(
            "INSERT INTO exception_list (session_id, allowed_channel_id, allowed_alias) VALUES (?, ?, ?)",
            (session_id, allowed_channel, alias)
        )
        self.execute_query("UPDATE db_metadata SET value = datetime('now'), updated_at = datetime('now') WHERE key = 'last_modified'")

        print(f"Added exception: {allowed_channel} can now route to {isolated_channel}")

    def remove_exception(self, isolated_channel, allowed_channel):
        """Remove an exception for a channel"""
        # Get active session
        results = self.execute_query(
            "SELECT session_id FROM isolation_sessions WHERE channel_id = ? AND status = 'active'",
            (isolated_channel,)
        )

        if not results:
            print(f"Channel {isolated_channel} is not currently isolated")
            return

        session_id = results[0][0]

        # Remove exception
        self.execute_query(
            "DELETE FROM exception_list WHERE session_id = ? AND allowed_channel_id = ?",
            (session_id, allowed_channel)
        )
        self.execute_query("UPDATE db_metadata SET value = datetime('now'), updated_at = datetime('now') WHERE key = 'last_modified'")

        print(f"Removed exception: {allowed_channel} can no longer route to {isolated_channel}")

    def list_isolated(self):
        """List all isolated channels"""
        results = self.execute_query("""
            SELECT
                channel_id,
                channel_alias,
                start_timestamp,
                total_attempts,
                total_allowed,
                total_rejected
            FROM isolation_sessions
            WHERE status = 'active'
            ORDER BY start_timestamp DESC
        """)

        if not results:
            print("No channels are currently isolated")
            return

        headers = ["Channel ID", "Alias", "Started", "Attempts", "Allowed", "Rejected"]

        # Format the data
        formatted_results = []
        for row in results:
            channel_id = row[0]
            alias = row[1] or "N/A"
            started = datetime.fromisoformat(row[2]).strftime("%Y-%m-%d %H:%M")
            formatted_results.append([channel_id, alias, started] + list(row[3:]))

        print("\nCurrently Isolated Channels:")
        print(tabulate(formatted_results, headers=headers, tablefmt="grid"))

    def show_exceptions(self, channel_id):
        """Show exceptions for an isolated channel"""
        # Get active session
        results = self.execute_query(
            "SELECT session_id FROM isolation_sessions WHERE channel_id = ? AND status = 'active'",
            (channel_id,)
        )

        if not results:
            print(f"Channel {channel_id} is not currently isolated")
            return

        session_id = results[0][0]

        # Get exceptions
        exceptions = self.execute_query("""
            SELECT
                allowed_channel_id,
                allowed_alias,
                added_timestamp
            FROM exception_list
            WHERE session_id = ?
            ORDER BY added_timestamp DESC
        """, (session_id,))

        if not exceptions:
            print(f"No exceptions configured for channel {channel_id}")
            return

        headers = ["Allowed Channel", "Alias", "Added"]
        formatted_results = []

        for row in exceptions:
            channel = row[0]
            alias = row[1] or "N/A"
            added = datetime.fromisoformat(row[2]).strftime("%Y-%m-%d %H:%M")
            formatted_results.append([channel, alias, added])

        print(f"\nExceptions for channel {channel_id}:")
        print(tabulate(formatted_results, headers=headers, tablefmt="grid"))

    def show_history(self, channel_id=None):
        """Show isolation history"""
        if channel_id:
            query = """
                SELECT
                    session_id,
                    channel_id,
                    channel_alias,
                    start_timestamp,
                    end_timestamp,
                    status,
                    total_attempts,
                    total_rejected,
                    total_allowed
                FROM isolation_sessions
                WHERE channel_id = ?
                ORDER BY start_timestamp DESC
                LIMIT 10
            """
            params = (channel_id,)
        else:
            query = """
                SELECT
                    session_id,
                    channel_id,
                    channel_alias,
                    start_timestamp,
                    end_timestamp,
                    status,
                    total_attempts,
                    total_rejected,
                    total_allowed
                FROM isolation_sessions
                ORDER BY start_timestamp DESC
                LIMIT 20
            """
            params = None

        results = self.execute_query(query, params)

        if not results:
            print("No isolation history found")
            return

        headers = ["Session", "Channel", "Alias", "Started", "Ended", "Status", "Attempts", "Rejected", "Allowed"]
        formatted_results = []

        for row in results:
            session_id = row[0]
            channel = row[1][:12] + "..." if len(row[1]) > 12 else row[1]
            alias = (row[2] or "N/A")[:15]
            started = datetime.fromisoformat(row[3]).strftime("%Y-%m-%d %H:%M")
            ended = datetime.fromisoformat(row[4]).strftime("%Y-%m-%d %H:%M") if row[4] else "N/A"
            status = row[5]
            formatted_results.append([session_id, channel, alias, started, ended, status] + list(row[6:]))

        print("\nIsolation History:")
        print(tabulate(formatted_results, headers=headers, tablefmt="grid"))

    def show_attempts(self, session_id):
        """Show HTLC attempts for a session"""
        # Verify session exists
        session = self.execute_query(
            "SELECT channel_id, status FROM isolation_sessions WHERE session_id = ?",
            (session_id,)
        )

        if not session:
            print(f"Session {session_id} not found")
            return

        channel_id, status = session[0]

        # Get attempts
        attempts = self.execute_query("""
            SELECT
                source_channel_id,
                source_alias,
                amount_msat,
                decision,
                outcome,
                timestamp
            FROM htlc_attempts
            WHERE session_id = ?
            ORDER BY timestamp DESC
            LIMIT 50
        """, (session_id,))

        if not attempts:
            print(f"No HTLC attempts found for session {session_id}")
            return

        print(f"\nHTLC Attempts for Session {session_id}")
        print(f"Isolated Channel: {channel_id} (Status: {status})\n")

        headers = ["Source Channel", "Alias", "Amount (sats)", "Decision", "Outcome", "Time"]
        formatted_results = []

        for row in attempts:
            source = row[0][:16] + "..." if len(row[0]) > 16 else row[0]
            alias = row[1] or "N/A"
            amount_sats = row[2] / 1000 if row[2] else 0
            decision = row[3]
            outcome = row[4] or "N/A"
            timestamp = datetime.fromisoformat(row[5]).strftime("%Y-%m-%d %H:%M:%S")
            formatted_results.append([source, alias, f"{amount_sats:.3f}", decision, outcome, timestamp])

        print(tabulate(formatted_results, headers=headers, tablefmt="grid"))

    def show_stats(self):
        """Show overall statistics"""
        # Active sessions
        active = self.execute_query(
            "SELECT COUNT(*) FROM isolation_sessions WHERE status = 'active'"
        )[0][0]

        # Total sessions
        total = self.execute_query(
            "SELECT COUNT(*) FROM isolation_sessions"
        )[0][0]

        # Total attempts
        attempts = self.execute_query(
            "SELECT COUNT(*) FROM htlc_attempts"
        )[0][0]

        # Breakdown
        breakdown = self.execute_query("""
            SELECT
                SUM(CASE WHEN decision = 'rejected' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN decision = 'allowed' THEN 1 ELSE 0 END) as allowed
            FROM htlc_attempts
        """)[0]

        print("\nChannel Isolator Statistics")
        print("=" * 40)
        print(f"Active Isolations:    {active}")
        print(f"Total Sessions:       {total}")
        print(f"Total HTLC Attempts:  {attempts}")
        print(f"  - Rejected:         {breakdown[0] or 0}")
        print(f"  - Allowed:          {breakdown[1] or 0}")


def main():
    parser = argparse.ArgumentParser(description='Channel Isolator CLI Management Tool')
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Isolate command
    isolate_parser = subparsers.add_parser('isolate', help='Start isolating a channel')
    isolate_parser.add_argument('channel_id', help='Channel ID to isolate')
    isolate_parser.add_argument('--alias', help='Channel alias for reference')

    # Stop command
    stop_parser = subparsers.add_parser('stop', help='Stop isolating a channel')
    stop_parser.add_argument('channel_id', help='Channel ID to stop isolating')

    # Add exception command
    add_exc_parser = subparsers.add_parser('add-exception', help='Add exception for a channel')
    add_exc_parser.add_argument('isolated_channel', help='Isolated channel ID')
    add_exc_parser.add_argument('allowed_channel', help='Channel ID to allow')
    add_exc_parser.add_argument('--alias', help='Allowed channel alias')

    # Remove exception command
    rm_exc_parser = subparsers.add_parser('remove-exception', help='Remove exception for a channel')
    rm_exc_parser.add_argument('isolated_channel', help='Isolated channel ID')
    rm_exc_parser.add_argument('allowed_channel', help='Channel ID to disallow')

    # List command
    list_parser = subparsers.add_parser('list', help='List isolated channels')

    # Show exceptions command
    show_exc_parser = subparsers.add_parser('exceptions', help='Show exceptions for a channel')
    show_exc_parser.add_argument('channel_id', help='Channel ID')

    # History command
    history_parser = subparsers.add_parser('history', help='Show isolation history')
    history_parser.add_argument('--channel', help='Filter by channel ID')

    # Attempts command
    attempts_parser = subparsers.add_parser('attempts', help='Show HTLC attempts for a session')
    attempts_parser.add_argument('session_id', type=int, help='Session ID')

    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show overall statistics')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cli = ChannelIsolatorCLI()

    if args.command == 'isolate':
        cli.isolate_channel(args.channel_id, args.alias)
    elif args.command == 'stop':
        cli.stop_isolation(args.channel_id)
    elif args.command == 'add-exception':
        cli.add_exception(args.isolated_channel, args.allowed_channel, args.alias)
    elif args.command == 'remove-exception':
        cli.remove_exception(args.isolated_channel, args.allowed_channel)
    elif args.command == 'list':
        cli.list_isolated()
    elif args.command == 'exceptions':
        cli.show_exceptions(args.channel_id)
    elif args.command == 'history':
        cli.show_history(args.channel)
    elif args.command == 'attempts':
        cli.show_attempts(args.session_id)
    elif args.command == 'stats':
        cli.show_stats()


if __name__ == "__main__":
    main()