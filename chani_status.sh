#!/bin/bash
echo "=== ISOLATED CHANNELS ==="
~/channel_isolator/channel-isolator-cli list
echo
echo "=== EXCEPTIONS ==="
for chan in $(sqlite3 ~/channel_isolator/channel_isolator.db "SELECT channel_id FROM isolation_sessions WHERE status = 'active'"); do
    ~/channel_isolator/channel-isolator-cli exceptions $chan
    echo
done
echo "=== STATISTICS ==="
~/channel_isolator/channel-isolator-cli stats
