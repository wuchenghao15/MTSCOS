#!/usr/bin/env python3
"""手调 sys_archive_engine._heartbeat() 实证心跳函数好坏 + 回读验证."""
import sqlite3
import sys

sys.path.insert(0, '/Users/wuchenghao/MTSCOS_AI_Project/_runtime/auto_daemons')
import sys_archive_engine as m  # noqa

m._heartbeat()
c = sqlite3.connect('/Users/wuchenghao/MTSCOS_AI_Project/flask-app/database/app.db',
                    timeout=30)
row = c.execute("SELECT last_heartbeat, pid, status FROM mt_daemon_registry "
                "WHERE process_name='sys_archive_engine'").fetchone()
print('手调后 hb=%s pid=%s status=%s' % row)
