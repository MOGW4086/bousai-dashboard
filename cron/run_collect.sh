#!/bin/bash
cd /root/bousai-dashboard
source .venv/bin/activate 2>/dev/null || . .venv/bin/activate
python scheduler/collect_all.py >> /root/bousai-dashboard/logs/collect.log 2>&1
