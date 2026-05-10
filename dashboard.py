#!/usr/bin/env python3
"""
Channel Isolator Web Dashboard
A clean, secure browser interface for managing your isolated channels.
Replicates all channel-isolator-cli functionality via the shared SQLite DB.
The running isolator service picks up changes automatically.

Run with: python channel_isolator_dashboard.py
Access at http://localhost:8081 (or your node's IP:port after firewall allow)
"""

import os
import sqlite3
import time
from datetime import datetime
from flask import (
    Flask, render_template_string, request, redirect, url_for,
    session, flash, jsonify
)
from functools import wraps

# ============== CONFIG ==============
DB_PATH = os.path.expanduser("~/channel_isolator/channel_isolator.db")
DASH_PASSWORD = os.environ.get("CHANNEL_ISOLATOR_DASHBOARD_PASSWORD", "changeme123")
PORT = int(os.environ.get("DASH_PORT", 8081))
HOST = "0.0.0.0"  # Change to 127.0.0.1 for localhost-only

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# ============== HELPERS ==============
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash("Please log in to access the dashboard.", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_db_connection():
    """Connect to the Channel Isolator SQLite DB (same as CLI and service)."""
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def execute_query(query, params=None, fetch=True):
    """Run a query and optionally fetch results. Matches CLI logic."""
    conn = get_db_connection()
    if conn is None:
        return [] if fetch else None
    try:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        if fetch:
            results = cursor.fetchall()
            return [dict(row) for row in results]
        else:
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()

def update_last_modified():
    """Signal the running isolator service that config changed (same as CLI)."""
    execute_query(
        "UPDATE db_metadata SET value = datetime('now'), updated_at = datetime('now') WHERE key = 'last_modified'",
        fetch=False
    )

def format_timestamp(ts):
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M")
    except:
        return ts

# ============== ROUTES ==============
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == DASH_PASSWORD:
            session['logged_in'] = True
            flash("Welcome back! Dashboard unlocked.", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Incorrect password. Try again.", "error")
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash("Logged out successfully.", "success")
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    conn = get_db_connection()
    if conn is None:
        flash("Database not found! Please run the Channel Isolator service first to initialize it.", "error")
        return render_template_string(DASHBOARD_HTML,
            active_isolations=[],
            exceptions=[],
            stats={},
            recent_attempts=[],
            history=[])

    # Active isolations (with stats)
    active_isolations = execute_query("""
        SELECT session_id, channel_id, channel_alias, start_timestamp,
               total_attempts, total_allowed, total_rejected
        FROM isolation_sessions
        WHERE status = 'active'
        ORDER BY start_timestamp DESC
    """)

    # All exceptions (joined with channel info)
    exceptions = execute_query("""
        SELECT e.exception_id, e.allowed_channel_id, e.allowed_alias,
               s.channel_id as isolated_channel_id, s.channel_alias as isolated_alias
        FROM exception_list e
        JOIN isolation_sessions s ON e.session_id = s.session_id
        WHERE s.status = 'active'
        ORDER BY s.start_timestamp DESC, e.added_timestamp DESC
    """)

    # Group exceptions by isolated channel for clearer categorized display
    exception_groups = []
    for iso in active_isolations:
        exs = [e for e in exceptions if e['isolated_channel_id'] == iso['channel_id']]
        exception_groups.append({
            'channel_id': iso['channel_id'],
            'channel_alias': iso['channel_alias'],
            'exceptions': exs
        })

    # Stats
    stats = {
        'active_count': len(active_isolations),
        'total_sessions': execute_query("SELECT COUNT(*) as c FROM isolation_sessions", fetch=True)[0]['c'],
        'total_attempts': execute_query("SELECT SUM(total_attempts) as s FROM isolation_sessions", fetch=True)[0]['s'] or 0,
        'total_allowed': execute_query("SELECT SUM(total_allowed) as s FROM isolation_sessions", fetch=True)[0]['s'] or 0,
        'total_rejected': execute_query("SELECT SUM(total_rejected) as s FROM isolation_sessions", fetch=True)[0]['s'] or 0,
    }

    # Recent HTLC attempts (last 15)
    recent_attempts = execute_query("""
        SELECT h.timestamp, h.source_channel_id, h.source_alias, h.amount_msat,
               h.decision, h.outcome, s.channel_id as isolated_channel
        FROM htlc_attempts h
        JOIN isolation_sessions s ON h.session_id = s.session_id
        ORDER BY h.timestamp DESC
        LIMIT 15
    """)

    # Recent history (last 10 completed)
    history = execute_query("""
        SELECT session_id, channel_id, channel_alias, start_timestamp, end_timestamp,
               total_attempts, total_allowed, total_rejected
        FROM isolation_sessions
        WHERE status = 'completed'
        ORDER BY end_timestamp DESC
        LIMIT 10
    """)

    return render_template_string(DASHBOARD_HTML,
        active_isolations=active_isolations,
        exceptions=exceptions,
        exception_groups=exception_groups,
        stats=stats,
        recent_attempts=recent_attempts,
        history=history,
        format_timestamp=format_timestamp
    )

@app.route('/isolate', methods=['POST'])
@login_required
def isolate_channel():
    channel_id = request.form.get('channel_id', '').strip()
    alias = request.form.get('alias', '').strip() or None

    if not channel_id:
        flash("Channel ID is required.", "error")
        return redirect(url_for('dashboard'))

    # Check if already active
    existing = execute_query(
        "SELECT 1 FROM isolation_sessions WHERE channel_id = ? AND status = 'active'",
        (channel_id,)
    )
    if existing:
        flash(f"Channel {channel_id} is already isolated.", "error")
        return redirect(url_for('dashboard'))

    # Insert new session (same as CLI)
    execute_query(
        "INSERT INTO isolation_sessions (channel_id, channel_alias) VALUES (?, ?)",
        (channel_id, alias),
        fetch=False
    )
    update_last_modified()
    flash(f"✅ Channel {channel_id} is now isolated! The service will pick it up shortly.", "success")
    return redirect(url_for('dashboard'))

@app.route('/stop/<channel_id>')
@login_required
def stop_isolation(channel_id):
    result = execute_query(
        """UPDATE isolation_sessions
           SET end_timestamp = CURRENT_TIMESTAMP, status = 'completed'
           WHERE channel_id = ? AND status = 'active'""",
        (channel_id,),
        fetch=False
    )
    if result:  # rows affected, but since fetch=False we check differently
        update_last_modified()
        flash(f"🛑 Isolation stopped for channel {channel_id}.", "success")
    else:
        flash("Channel not found or already stopped.", "error")
    return redirect(url_for('dashboard'))

@app.route('/add_exception', methods=['POST'])
@login_required
def add_exception():
    isolated_id = request.form.get('isolated_id', '').strip()
    allowed_id = request.form.get('allowed_id', '').strip()
    allowed_alias = request.form.get('allowed_alias', '').strip() or None

    if not isolated_id or not allowed_id:
        flash("Both isolated channel and allowed channel IDs are required.", "error")
        return redirect(url_for('dashboard'))

    # Find active session for isolated channel
    session_row = execute_query(
        "SELECT session_id FROM isolation_sessions WHERE channel_id = ? AND status = 'active'",
        (isolated_id,)
    )
    if not session_row:
        flash(f"No active isolation found for channel {isolated_id}.", "error")
        return redirect(url_for('dashboard'))

    session_id = session_row[0]['session_id']

    # Check duplicate
    dup = execute_query(
        "SELECT 1 FROM exception_list WHERE session_id = ? AND allowed_channel_id = ?",
        (session_id, allowed_id)
    )
    if dup:
        flash("That exception already exists.", "error")
        return redirect(url_for('dashboard'))

    execute_query(
        "INSERT INTO exception_list (session_id, allowed_channel_id, allowed_alias) VALUES (?, ?, ?)",
        (session_id, allowed_id, allowed_alias),
        fetch=False
    )
    update_last_modified()
    flash(f"✅ Exception added: {allowed_id} can now route to {isolated_id}.", "success")
    return redirect(url_for('dashboard'))

@app.route('/remove_exception/<int:exception_id>')
@login_required
def remove_exception(exception_id):
    execute_query(
        "DELETE FROM exception_list WHERE exception_id = ?",
        (exception_id,),
        fetch=False
    )
    update_last_modified()
    flash("Exception removed successfully.", "success")
    return redirect(url_for('dashboard'))

@app.route('/api/stats')
@login_required
def api_stats():
    """Simple JSON endpoint for future auto-refresh or integrations."""
    stats = {
        'active_count': len(execute_query("SELECT 1 FROM isolation_sessions WHERE status = 'active'")),
        'timestamp': datetime.now().isoformat()
    }
    return jsonify(stats)

# ============== HTML TEMPLATES (Tailwind dark + modern) ==============
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Channel Isolator • Login</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
</head>
<body class="bg-zinc-950 text-zinc-200 flex items-center justify-center min-h-screen">
    <div class="max-w-md w-full mx-4">
        <div class="flex justify-center mb-8">
            <div class="flex items-center gap-3">
                <div class="w-12 h-12 bg-emerald-600 rounded-2xl flex items-center justify-center">
                    <i class="fa-solid fa-shield-halved text-white text-3xl"></i>
                </div>
                <div>
                    <h1 class="text-3xl font-bold tracking-tight">Channel Isolator</h1>
                    <p class="text-emerald-400 text-sm -mt-1">Lightning Node Control</p>
                </div>
            </div>
        </div>

        <div class="bg-zinc-900 border border-zinc-800 rounded-3xl p-8 shadow-2xl">
            <h2 class="text-2xl font-semibold mb-6 text-center">Sign in to Dashboard</h2>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="mb-4 p-3 rounded-xl text-sm {% if category == 'error' %}bg-red-950 text-red-400 border border-red-900{% else %}bg-emerald-950 text-emerald-400 border border-emerald-900{% endif %}">
                            {{ message }}
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <form method="POST" class="space-y-6">
                <div>
                    <label class="block text-sm font-medium mb-2 text-zinc-400">Password</label>
                    <div class="relative">
                        <input type="password" name="password" required autofocus
                               class="w-full bg-zinc-950 border border-zinc-800 focus:border-emerald-600 rounded-2xl px-4 py-3 text-lg placeholder-zinc-500 outline-none transition">
                        <i class="fa-solid fa-lock absolute right-4 top-4 text-zinc-600"></i>
                    </div>
                </div>
                <button type="submit"
                        class="w-full bg-emerald-600 hover:bg-emerald-500 transition-colors text-white font-semibold py-3.5 rounded-2xl flex items-center justify-center gap-2">
                    <i class="fa-solid fa-sign-in-alt"></i>
                    <span>Unlock Dashboard</span>
                </button>
            </form>

            <p class="text-center text-xs text-zinc-500 mt-6">Protected • Local node only</p>
        </div>
    </div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Channel Isolator Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
        .glass { background: rgba(24, 24, 27, 0.8); backdrop-filter: blur(12px); }
        .metric { transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1); }
        .metric:hover { transform: translateY(-2px); }
        .nav-active { background: #18181b; color: #10b981; border-radius: 9999px; }
        .section { scroll-margin-top: 80px; }
    </style>
</head>
<body class="bg-zinc-950 text-zinc-200">
    <!-- Top nav -->
    <nav class="border-b border-zinc-800 bg-zinc-900/80 backdrop-blur-xl sticky top-0 z-50">
        <div class="max-w-screen-2xl mx-auto px-8 py-4 flex items-center justify-between">
            <div class="flex items-center gap-4">
                <div class="flex items-center gap-3">
                    <div class="w-9 h-9 bg-emerald-600 rounded-2xl flex items-center justify-center">
                        <i class="fa-solid fa-shield-halved text-white text-xl"></i>
                    </div>
                    <div>
                        <span class="font-semibold text-xl tracking-tight">Channel Isolator</span>
                        <span class="text-emerald-500 text-xs align-super ml-1">v1.0</span>
                    </div>
                </div>
                <div class="hidden md:flex items-center gap-2 text-xs px-3 py-1 bg-zinc-900 rounded-full border border-zinc-800">
                    <div class="w-2 h-2 bg-emerald-500 rounded-full animate-pulse"></div>
                    <span class="text-emerald-400 font-mono">SERVICE ACTIVE</span>
                </div>
            </div>

            <div class="flex items-center gap-3">
                <button onclick="window.location.reload()"
                        class="flex items-center gap-2 px-4 py-2 text-sm rounded-2xl bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 transition">
                    <i class="fa-solid fa-sync-alt"></i>
                    <span class="hidden md:inline">Refresh</span>
                </button>

                <div class="relative group">
                    <button class="flex items-center gap-2 px-3 py-2 rounded-2xl hover:bg-zinc-900 transition">
                        <i class="fa-solid fa-user-circle text-xl text-zinc-400"></i>
                    </button>
                    <div class="absolute right-0 mt-2 w-48 bg-zinc-900 border border-zinc-800 rounded-2xl shadow-xl py-1 hidden group-hover:block">
                        <a href="{{ url_for('logout') }}" class="block px-4 py-2 text-sm hover:bg-zinc-800 flex items-center gap-2">
                            <i class="fa-solid fa-sign-out-alt w-4"></i> Logout
                        </a>
                    </div>
                </div>
            </div>
        </div>
    </nav>

    <div class="max-w-screen-2xl mx-auto px-8 py-8">

        <!-- Flash messages -->
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                <div class="mb-6 space-y-2">
                    {% for category, message in messages %}
                        <div class="px-5 py-3 rounded-2xl flex items-start gap-3 text-sm border {% if category == 'error' %}bg-red-950/60 border-red-900 text-red-400{% else %}bg-emerald-950/60 border-emerald-900 text-emerald-400{% endif %}">
                            <i class="fa-solid {% if category == 'error' %}fa-exclamation-circle{% else %}fa-check-circle{% endif %} mt-0.5"></i>
                            <span>{{ message }}</span>
                        </div>
                    {% endfor %}
                </div>
            {% endif %}
        {% endwith %}

        <!-- Hero / Quick stats -->
        <div class="flex flex-col md:flex-row md:items-end md:justify-between mb-8 gap-4">
            <div>
                <h1 class="text-4xl font-semibold tracking-tighter">Control Center</h1>
                <p class="text-zinc-500 mt-1">Manage isolated channels and exceptions in real time</p>
            </div>

            <div class="flex items-center gap-3 text-sm">
                <div class="px-4 py-2 bg-zinc-900 border border-zinc-800 rounded-2xl flex items-center gap-2">
                    <i class="fa-solid fa-database text-emerald-500"></i>
                    <span class="font-mono text-xs">DB: {{ active_isolations|length }} active</span>
                </div>
                <a href="#isolate"
                   class="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 transition rounded-2xl text-sm font-medium flex items-center gap-2">
                    <i class="fa-solid fa-plus"></i>
                    <span>Isolate Channel</span>
                </a>
            </div>
        </div>

        <!-- Metrics -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <div class="metric glass border border-zinc-800 rounded-3xl p-5">
                <div class="flex justify-between items-start">
                    <div>
                        <div class="text-emerald-400 text-xs tracking-widest font-medium">ACTIVE</div>
                        <div class="text-4xl font-semibold mt-1">{{ stats.active_count }}</div>
                    </div>
                    <i class="fa-solid fa-link text-3xl text-emerald-600/70"></i>
                </div>
                <div class="text-xs text-zinc-500 mt-3">Isolated channels</div>
            </div>

            <div class="metric glass border border-zinc-800 rounded-3xl p-5">
                <div class="flex justify-between items-start">
                    <div>
                        <div class="text-amber-400 text-xs tracking-widest font-medium">ATTEMPTS</div>
                        <div class="text-4xl font-semibold mt-1">{{ "{:,}".format(stats.total_attempts) }}</div>
                    </div>
                    <i class="fa-solid fa-exchange-alt text-3xl text-amber-600/70"></i>
                </div>
                <div class="text-xs text-zinc-500 mt-3">Total HTLCs processed</div>
            </div>

            <div class="metric glass border border-zinc-800 rounded-3xl p-5">
                <div class="flex justify-between items-start">
                    <div>
                        <div class="text-emerald-400 text-xs tracking-widest font-medium">ALLOWED</div>
                        <div class="text-4xl font-semibold mt-1">{{ "{:,}".format(stats.total_allowed) }}</div>
                    </div>
                    <i class="fa-solid fa-check-double text-3xl text-emerald-600/70"></i>
                </div>
                <div class="text-xs text-zinc-500 mt-3">Through exceptions</div>
            </div>

            <div class="metric glass border border-zinc-800 rounded-3xl p-5">
                <div class="flex justify-between items-start">
                    <div>
                        <div class="text-red-400 text-xs tracking-widest font-medium">BLOCKED</div>
                        <div class="text-4xl font-semibold mt-1">{{ "{:,}".format(stats.total_rejected) }}</div>
                    </div>
                    <i class="fa-solid fa-ban text-3xl text-red-600/70"></i>
                </div>
                <div class="text-xs text-zinc-500 mt-3">Rejected HTLCs</div>
            </div>
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-12 gap-6">

            <!-- Active Isolations -->
            <div class="xl:col-span-7 glass border border-zinc-800 rounded-3xl overflow-hidden" id="active">
                <div class="px-6 py-4 border-b border-zinc-800 flex items-center justify-between bg-zinc-900/50">
                    <div class="flex items-center gap-3">
                        <i class="fa-solid fa-shield-halved text-emerald-500"></i>
                        <h2 class="font-semibold">Active Isolations</h2>
                        <span class="text-xs px-2 py-0.5 bg-emerald-950 text-emerald-500 rounded-full">{{ active_isolations|length }}</span>
                    </div>
                    <span class="text-xs text-zinc-500 font-mono">Auto-updated by service</span>
                </div>

                {% if active_isolations %}
                <div class="overflow-x-auto">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="text-left text-xs text-zinc-500 border-b border-zinc-800">
                                <th class="px-6 py-3 font-medium">Channel ID / Alias</th>
                                <th class="px-6 py-3 font-medium">Started</th>
                                <th class="px-6 py-3 font-medium text-center">Attempts</th>
                                <th class="px-6 py-3 font-medium text-center">Allowed</th>
                                <th class="px-6 py-3 font-medium text-center">Blocked</th>
                                <th class="px-6 py-3"></th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-zinc-800">
                            {% for iso in active_isolations %}
                            <tr class="hover:bg-zinc-900/60 transition">
                                <td class="px-6 py-4 font-mono text-xs">
                                    <div class="font-medium text-zinc-300">{{ iso.channel_id }}</div>
                                    {% if iso.channel_alias %}
                                    <div class="text-emerald-400 text-xs">{{ iso.channel_alias }}</div>
                                    {% endif %}
                                </td>
                                <td class="px-6 py-4 text-xs text-zinc-400">{{ format_timestamp(iso.start_timestamp) }}</td>
                                <td class="px-6 py-4 text-center">
                                    <span class="font-mono text-sm">{{ iso.total_attempts or 0 }}</span>
                                </td>
                                <td class="px-6 py-4 text-center">
                                    <span class="text-emerald-400 font-medium">{{ iso.total_allowed or 0 }}</span>
                                </td>
                                <td class="px-6 py-4 text-center">
                                    <span class="text-red-400 font-medium">{{ iso.total_rejected or 0 }}</span>
                                </td>
                                <td class="px-6 py-4 text-right">
                                    <a href="{{ url_for('stop_isolation', channel_id=iso.channel_id) }}"
                                       onclick="return confirm('Stop isolating this channel?')"
                                       class="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs bg-red-950 hover:bg-red-900 text-red-400 rounded-2xl border border-red-900 transition">
                                        <i class="fa-solid fa-stop"></i>
                                        <span>Stop</span>
                                    </a>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% else %}
                <div class="px-6 py-12 text-center text-zinc-500">
                    <i class="fa-solid fa-link-slash text-4xl mb-4 opacity-50"></i>
                    <p>No channels currently isolated.</p>
                    <p class="text-xs mt-1">Use the form below to start protecting liquidity.</p>
                </div>
                {% endif %}
            </div>

            <!-- Quick Isolate -->
            <div class="xl:col-span-5 glass border border-zinc-800 rounded-3xl p-6" id="isolate">
                <h2 class="font-semibold flex items-center gap-3 mb-4">
                    <i class="fa-solid fa-plus-circle text-emerald-500"></i>
                    <span>Isolate New Channel</span>
                </h2>
                <form method="POST" action="{{ url_for('isolate_channel') }}" class="space-y-4">
                    <div>
                        <label class="block text-xs font-medium text-zinc-400 mb-1.5">CHANNEL ID</label>
                        <input type="text" name="channel_id" required placeholder="e.g. 1234567890123456789"
                               class="w-full bg-zinc-950 border border-zinc-800 focus:border-emerald-600 rounded-2xl px-4 py-2.5 text-sm font-mono placeholder:text-zinc-600 outline-none">
                    </div>
                    <div>
                        <label class="block text-xs font-medium text-zinc-400 mb-1.5">ALIAS (OPTIONAL)</label>
                        <input type="text" name="alias" placeholder="My Premium Route"
                               class="w-full bg-zinc-950 border border-zinc-800 focus:border-emerald-600 rounded-2xl px-4 py-2.5 text-sm placeholder:text-zinc-600 outline-none">
                    </div>
                    <button type="submit"
                            class="w-full mt-2 bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 transition-all text-white py-3 rounded-2xl font-medium flex items-center justify-center gap-2 text-sm">
                        <i class="fa-solid fa-shield-alt"></i>
                        <span>START ISOLATION</span>
                    </button>
                </form>
                <p class="text-[10px] text-center text-zinc-500 mt-3">The background service will begin blocking incoming HTLCs within ~1 second.</p>
            </div>

            <!-- Exceptions -->
            <div class="xl:col-span-12 glass border border-zinc-800 rounded-3xl overflow-hidden" id="exceptions">
                <div class="px-6 py-4 border-b border-zinc-800 flex items-center justify-between bg-zinc-900/50">
                    <div class="flex items-center gap-3">
                        <i class="fa-solid fa-user-check text-amber-500"></i>
                        <h2 class="font-semibold">Exceptions (Allowed Routes)</h2>
                    </div>
                    <span class="text-xs px-2.5 py-px bg-amber-950 text-amber-500 rounded-full">{{ exceptions|length }} rules</span>
                </div>

                <div class="p-6 space-y-6">
                    {% if exception_groups %}
                        {% for group in exception_groups %}
                        <div class="border border-zinc-800 rounded-2xl p-4 bg-zinc-950">
                            <!-- Isolated Channel Header -->
                            <div class="flex items-center justify-between mb-3">
                                <div>
                                    <div class="font-mono text-sm text-emerald-400">{{ group.channel_id }}</div>
                                    {% if group.channel_alias %}
                                    <div class="text-emerald-300 text-sm font-medium">{{ group.channel_alias }}</div>
                                    {% else %}
                                    <div class="text-xs text-zinc-500 italic">No alias set</div>
                                    {% endif %}
                                </div>
                                <span class="text-xs px-2 py-0.5 bg-amber-950 text-amber-400 rounded-full">{{ group.exceptions|length }} exceptions</span>
                            </div>

                            {% if group.exceptions %}
                            <div class="space-y-2 pl-1">
                                {% for ex in group.exceptions %}
                                <div class="flex items-center justify-between bg-zinc-900 border border-zinc-700 rounded-xl px-4 py-2.5 group hover:border-amber-900 transition">
                                    <div class="flex items-center gap-3 text-sm">
                                        <div>
                                            <span class="font-mono text-xs text-amber-400">{{ ex.allowed_channel_id }}</span>
                                            {% if ex.allowed_alias %}
                                            <span class="text-[10px] text-zinc-400 ml-1">({{ ex.allowed_alias }})</span>
                                            {% endif %}
                                        </div>
                                        <div class="text-xs text-zinc-500">can route into this channel</div>
                                    </div>
                                    <a href="{{ url_for('remove_exception', exception_id=ex.exception_id) }}"
                                       onclick="return confirm('Remove this exception?')"
                                       class="opacity-60 group-hover:opacity-100 text-red-400 hover:text-red-500 px-2 py-1 rounded-xl transition">
                                        <i class="fa-solid fa-times"></i>
                                    </a>
                                </div>
                                {% endfor %}
                            </div>
                            {% else %}
                            <div class="pl-1 text-xs text-zinc-500 italic py-1">No exceptions yet — all incoming HTLCs to this channel are blocked.</div>
                            {% endif %}
                        </div>
                        {% endfor %}
                    {% else %}
                    <div class="text-center py-8 text-sm text-zinc-500">
                        <i class="fa-solid fa-user-slash text-3xl mb-3 opacity-40"></i>
                        <p>No exceptions configured yet.</p>
                        <p class="text-xs mt-1">Add trusted channels below to allow specific routes.</p>
                    </div>
                    {% endif %}

                    <!-- Add Exception Form -->
                    <div class="mt-6 pt-6 border-t border-zinc-800">
                        <h3 class="text-sm font-medium mb-3 text-zinc-400 flex items-center gap-2">
                            <i class="fa-solid fa-plus text-amber-500"></i> Add New Exception
                        </h3>
                        <form method="POST" action="{{ url_for('add_exception') }}" class="grid grid-cols-1 md:grid-cols-12 gap-3">
                            <div class="md:col-span-5">
                                <label class="block text-[10px] text-zinc-500 mb-1">ISOLATED CHANNEL ID</label>
                                <input type="text" name="isolated_id" placeholder="e.g. 1234567890123456789" required
                                       class="w-full bg-zinc-950 border border-zinc-800 focus:border-amber-600 rounded-2xl px-4 py-2 text-sm font-mono placeholder:text-zinc-600 outline-none">
                            </div>
                            <div class="md:col-span-5">
                                <label class="block text-[10px] text-zinc-500 mb-1">ALLOWED SOURCE CHANNEL ID</label>
                                <input type="text" name="allowed_id" placeholder="e.g. 9876543210987654321" required
                                       class="w-full bg-zinc-950 border border-zinc-800 focus:border-amber-600 rounded-2xl px-4 py-2 text-sm font-mono placeholder:text-zinc-600 outline-none">
                            </div>
                            <div class="md:col-span-2 flex items-end">
                                <button type="submit" class="w-full bg-amber-600 hover:bg-amber-500 active:bg-amber-700 transition-all text-white py-2.5 rounded-2xl text-sm font-medium flex items-center justify-center gap-2">
                                    <i class="fa-solid fa-check"></i> Add
                                </button>
                            </div>
                        </form>
                        <p class="text-[10px] text-center text-zinc-500 mt-2">The exception will be applied immediately by the running service.</p>
                    </div>
                </div>
            </div>

            <!-- Recent Attempts -->
            <div class="xl:col-span-7 glass border border-zinc-800 rounded-3xl overflow-hidden">
                <div class="px-6 py-4 border-b border-zinc-800 flex items-center justify-between">
                    <h2 class="font-semibold flex items-center gap-2"><i class="fa-solid fa-history text-zinc-400"></i> Recent HTLC Attempts</h2>
                    <span class="text-xs text-zinc-500">Last 15 • from isolated channels</span>
                </div>

                {% if recent_attempts %}
                <table class="w-full text-xs">
                    <thead class="text-zinc-500">
                        <tr class="border-b border-zinc-800">
                            <th class="px-6 py-2 text-left">Time</th>
                            <th class="px-6 py-2 text-left">Source → Isolated</th>
                            <th class="px-6 py-2 text-right">Amount (sat)</th>
                            <th class="px-6 py-2 text-center">Decision</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-zinc-800 text-xs">
                        {% for att in recent_attempts %}
                        <tr class="hover:bg-zinc-900/50">
                            <td class="px-6 py-3 text-zinc-400 font-mono">{{ format_timestamp(att.timestamp) }}</td>
                            <td class="px-6 py-3 font-mono">
                                <span class="text-amber-400">{{ att.source_channel_id }}</span>
                                <span class="text-zinc-600 mx-1">→</span>
                                <span class="text-emerald-400">{{ att.isolated_channel }}</span>
                            </td>
                            <td class="px-6 py-3 text-right font-mono">{{ (att.amount_msat / 1000)|int }}</td>
                            <td class="px-6 py-3 text-center">
                                {% if att.decision == 'allowed' %}
                                    <span class="px-2.5 py-px text-[10px] bg-emerald-950 text-emerald-400 rounded">ALLOWED</span>
                                {% else %}
                                    <span class="px-2.5 py-px text-[10px] bg-red-950 text-red-400 rounded">BLOCKED</span>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                {% else %}
                <div class="p-8 text-center text-sm text-zinc-500">No HTLC attempts recorded yet on isolated channels.</div>
                {% endif %}
            </div>

            <!-- History -->
            <div class="xl:col-span-5 glass border border-zinc-800 rounded-3xl p-6">
                <h2 class="font-semibold mb-4 flex items-center gap-2"><i class="fa-solid fa-archive text-zinc-400"></i> Recent History</h2>

                {% if history %}
                <div class="space-y-3 text-sm">
                    {% for h in history %}
                    <div class="flex justify-between items-start border-l-2 border-zinc-700 pl-3">
                        <div>
                            <div class="font-mono text-xs text-zinc-400">{{ h.channel_id }}</div>
                            <div class="text-xs text-zinc-500">{{ format_timestamp(h.start_timestamp) }} → {{ format_timestamp(h.end_timestamp) }}</div>
                        </div>
                        <div class="text-right text-xs">
                            <div><span class="text-emerald-400">{{ h.total_allowed or 0 }}</span> / <span class="text-red-400">{{ h.total_rejected or 0 }}</span></div>
                            <div class="text-[10px] text-zinc-500">{{ h.total_attempts or 0 }} total</div>
                        </div>
                    </div>
                    {% endfor %}
                </div>
                {% else %}
                <p class="text-sm text-zinc-500">No completed isolation sessions yet.</p>
                {% endif %}

                <div class="mt-6 text-[10px] text-center text-zinc-500 border-t border-zinc-800 pt-4">
                    Full history &amp; per-session attempts available via CLI: <span class="font-mono">channel-isolator-cli history</span>
                </div>
            </div>

        </div>

        <div class="mt-8 text-center text-[10px] text-zinc-500 flex items-center justify-center gap-2">
            <i class="fa-solid fa-info-circle"></i>
            <span>Changes made here are instantly visible to the running Channel Isolator service. No restart needed.</span>
        </div>
    </div>

    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        // Tailwind script
        function initializeTailwind() {
            document.documentElement.style.setProperty('--accent', '#10b981');
        }
        window.onload = initializeTailwind;

        // Optional: auto refresh every 60s (uncomment if desired)
        // setTimeout(() => window.location.reload(), 60000);
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    print(f"🚀 Channel Isolator Dashboard starting on http://{HOST}:{PORT}")
    print(f"   DB: {DB_PATH}")
    print(f"   Default password: {DASH_PASSWORD} (change via env var CHANNEL_ISOLATOR_DASHBOARD_PASSWORD)")
    print("   Press CTRL+C to stop.")
    app.run(host=HOST, port=PORT, debug=False)
