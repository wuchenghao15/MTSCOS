#!/bin/bash
# WAL auto-cleaner — 每 5 分钟清 mini Flask WAL 防止磁盘爆
# 注册: crontab -e → */5 * * * * /Users/wuchenghao/MTSCOS_AI_Project/flask-app/scripts/clean_wal.sh
APP="/Users/wuchenghao/MTSCOS_AI_Project/flask-app/database"
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/opt/homebrew/bin

# 1. 先看 db 大小
WAL_SIZE=$(ls -la "$APP/app.db-wal" 2>/dev/null | awk '{print $5}' || echo 0)
if [ "$WAL_SIZE" -gt 1048576000 ]; then  # > 1GB
    # 2. 杀所有 Python (释放 WAL 锁)
    pkill -9 python 2>/dev/null
    sleep 3
    # 3. TRUNCATE WAL
    sqlite3 "$APP/app.db" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null
    # 4. 硬删 WAL 文件 (保险)
    rm -f "$APP/app.db-wal" "$APP/app.db-shm" "$APP/backup_kernel.db-wal" "$APP/backup_kernel.db-shm"
    # 5. 清 /tmp
    rm -f /tmp/*.db /tmp/*.log /tmp/*.partial 2>/dev/null
    # 6. 重启 Flask
    cd /Users/wuchenghao/MTSCOS_AI_Project/flask-app
    export NODE_ROLE=SERVER VIKEY_BACKEND=sim
    nohup python3 -u modular_start.py --port=5001 >> /tmp/flask_wal.log 2>&1 &
    echo "[$(date)] WAL cleaned (${WAL_SIZE} bytes) → Flask restarted"
else
    :  # WAL 没爆, 不动
fi
