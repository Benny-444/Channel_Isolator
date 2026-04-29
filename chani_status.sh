#!/bin/bash
DB=~/channel_isolator/channel_isolator.db

echo "=== ISOLATED CHANNELS ==="
~/channel_isolator/channel-isolator-cli list
echo
echo "=== EXCEPTIONS ==="
for chan in $(sqlite3 "$DB" "SELECT channel_id FROM isolation_sessions WHERE status = 'active'"); do
    ~/channel_isolator/channel-isolator-cli exceptions "$chan"
    echo
done

echo "=== LAST 50 ALLOWED HTLCs ==="

ISOLATED_JSON=$(sqlite3 "$DB" "SELECT channel_id FROM isolation_sessions WHERE status = 'active'" | jq -R . | jq -s .)

if [ "$ISOLATED_JSON" = "[]" ]; then
    echo "No isolated channels currently active."
else
    ROWS=$(lncli fwdinghistory --max_events 10000 2>/dev/null | \
        jq -r --argjson isolated "$ISOLATED_JSON" '
            .forwarding_events
            | map(select(.chan_id_out as $out | $isolated | index($out)))
            | sort_by(.timestamp_ns | tonumber) | reverse | .[0:50]
            | .[]
            | [
                (.timestamp_ns | tonumber / 1000000000 | strflocaltime("%Y-%m-%d %H:%M")),
                .chan_id_in,
                (.peer_alias_in // "?"),
                .chan_id_out,
                (.peer_alias_out // "?"),
                ((.amt_out_msat | tonumber) / 1000 | floor | tostring),
                .fee_msat,
                (if (.amt_out_msat | tonumber) > 0
                 then ((.fee_msat | tonumber) * 1000000 / (.amt_out_msat | tonumber) | floor | tostring)
                 else "0" end)
              ]
            | @tsv
        ')

    if [ -z "$ROWS" ]; then
        echo "No forwards through isolated channels found in the last 10000 events."
    else
        {
            printf "TIME\tIN_SCID\tIN_ALIAS\tOUT_SCID\tOUT_ALIAS\tAMT_SAT\tFEE_MSAT\tPPM\n"
            echo "$ROWS"
        } | column -t -s $'\t'
    fi
fi
