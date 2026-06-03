#!/bin/bash
(crontab -l | grep -v "bousai-dashboard"; echo ""; echo "# ── bousai-dashboard ──────────────────────────"; echo "0 * * * * /root/bousai-dashboard/cron/run_collect.sh") | crontab -
