from core.db_path import get_db_path as _mtscos_get_db_path
#!/usr/bin/env python3
""" MTSCOS AI 通讯中心服务 ====================== 整合站内通知、邮件系统、短信系统、交流系统，提供统一的通讯管理。  核心模块： 1. 站内通知 - 通知发送、阅读、归档、批量操作、通知模板 2. 邮件系统 - 邮件发送、模板管理、邮件队列、发送记录 3. 短信系统 - 短信发送、模板管理、发送记录、验证码 4. 交流系统 - 用户间消息、群组交流、会话管理 """
import os
import re
import json
import uuid
import sqlite3
import logging
import threading
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

DATABASE_PATH = _mtscos_get_db_path('app.db')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('CommunicationCenterService')


class CommunicationCenterService:
    """通讯中心服务 - 整合通知、邮件、短信、交流系统"""

    def __init__(self):
        self._lock = threading.RLock()
        self._init_db()
        self._init_templates()

    def _get_connection(self):
        conn = sqlite3.connect(DATABASE_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # 扩展通知表（如果不存在则创建）
                cursor.execute(""" CREATE TABLE IF NOT EXISTS notifications ( id INTEGER PRIMARY KEY AUTOINCREMENT, notification_id TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL, title TEXT NOT NULL, content TEXT, type TEXT DEFAULT 'info', category TEXT DEFAULT 'system', priority TEXT DEFAULT 'normal', status TEXT DEFAULT 'unread', sender_id INTEGER, sender_name TEXT, action_url TEXT, action_text TEXT, metadata TEXT, expires_at TEXT, read_at TEXT, archived INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP ) """)

                # 兼容旧表：检查并添加缺失列
                cursor.execute("PRAGMA table_info(notifications)")
                existing_cols = {row[1] for row in cursor.fetchall()}
                new_columns = {
                    'category': "TEXT DEFAULT 'system'",
                    'priority': "TEXT DEFAULT 'normal'",
                    'sender_id': 'INTEGER',
                    'sender_name': 'TEXT',
                    'action_url': 'TEXT',
                    'action_text': 'TEXT',
                    'metadata': 'TEXT',
                    'expires_at': 'TEXT',
                    'read_at': 'TEXT',
                    'archived': 'INTEGER DEFAULT 0'
                }
                for col, col_def in new_columns.items():
                    if col not in existing_cols:
                        try:
                            cursor.execute(f"ALTER TABLE notifications ADD COLUMN {col} {col_def}")
                            logger.info(f"notifications表添加列: {col}")
                        except Exception:
                            pass

                # 邮件表
                cursor.execute(""" CREATE TABLE IF NOT EXISTS emails ( id INTEGER PRIMARY KEY AUTOINCREMENT, email_id TEXT UNIQUE NOT NULL, from_address TEXT NOT NULL, to_address TEXT NOT NULL, cc_address TEXT, bcc_address TEXT, subject TEXT NOT NULL, body_text TEXT, body_html TEXT, template_id TEXT, status TEXT DEFAULT 'pending', priority TEXT DEFAULT 'normal', retry_count INTEGER DEFAULT 0, max_retries INTEGER DEFAULT 3, error_message TEXT, sent_at TEXT, delivered_at TEXT, opened_at TEXT, created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP ) """)

                # 邮件模板表
                cursor.execute(""" CREATE TABLE IF NOT EXISTS email_templates ( id INTEGER PRIMARY KEY AUTOINCREMENT, template_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL, subject TEXT NOT NULL, body_text TEXT, body_html TEXT, category TEXT DEFAULT 'general', variables TEXT, is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP ) """)

                # 短信表
                cursor.execute(""" CREATE TABLE IF NOT EXISTS sms_messages ( id INTEGER PRIMARY KEY AUTOINCREMENT, sms_id TEXT UNIQUE NOT NULL, phone_number TEXT NOT NULL, content TEXT NOT NULL, template_id TEXT, sms_type TEXT DEFAULT 'notification', status TEXT DEFAULT 'pending', priority TEXT DEFAULT 'normal', retry_count INTEGER DEFAULT 0, max_retries INTEGER DEFAULT 3, provider TEXT DEFAULT 'default', provider_message_id TEXT, error_message TEXT, sent_at TEXT, delivered_at TEXT, created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP ) """)

                # 短信模板表
                cursor.execute(""" CREATE TABLE IF NOT EXISTS sms_templates ( id INTEGER PRIMARY KEY AUTOINCREMENT, template_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL, category TEXT DEFAULT 'general', variables TEXT, max_length INTEGER DEFAULT 70, is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP ) """)

                # 短信验证码表
                cursor.execute(""" CREATE TABLE IF NOT EXISTS sms_verification_codes ( id INTEGER PRIMARY KEY AUTOINCREMENT, code_id TEXT UNIQUE NOT NULL, phone_number TEXT NOT NULL, code TEXT NOT NULL, purpose TEXT DEFAULT 'login', expires_at TEXT NOT NULL, used INTEGER DEFAULT 0, used_at TEXT, attempt_count INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP ) """)

                # 交流会话表
                cursor.execute(""" CREATE TABLE IF NOT EXISTS chat_conversations ( id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT UNIQUE NOT NULL, conversation_type TEXT DEFAULT 'direct', name TEXT, creator_id INTEGER NOT NULL, participant_ids TEXT NOT NULL, last_message_id TEXT, last_message_preview TEXT, last_message_at TEXT, unread_count INTEGER DEFAULT 0, is_pinned INTEGER DEFAULT 0, is_muted INTEGER DEFAULT 0, status TEXT DEFAULT 'active', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP ) """)

                # 交流消息表
                cursor.execute(""" CREATE TABLE IF NOT EXISTS chat_messages ( id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT UNIQUE NOT NULL, conversation_id TEXT NOT NULL, sender_id INTEGER NOT NULL, sender_name TEXT, sender_avatar TEXT, message_type TEXT DEFAULT 'text', content TEXT NOT NULL, attachment_url TEXT, attachment_name TEXT, attachment_size INTEGER, reply_to_id TEXT, read_by TEXT, is_edited INTEGER DEFAULT 0, edited_at TEXT, is_deleted INTEGER DEFAULT 0, deleted_at TEXT, metadata TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP ) """)

                # 交流群组成员表
                cursor.execute(""" CREATE TABLE IF NOT EXISTS chat_participants ( id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, user_id INTEGER NOT NULL, role TEXT DEFAULT 'member', joined_at TEXT DEFAULT CURRENT_TIMESTAMP, last_read_message_id TEXT, last_read_at TEXT, is_active INTEGER DEFAULT 1, UNIQUE(conversation_id, user_id) ) """)

                # 通讯偏好设置表
                cursor.execute(""" CREATE TABLE IF NOT EXISTS communication_preferences ( id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL UNIQUE, email_enabled INTEGER DEFAULT 1, sms_enabled INTEGER DEFAULT 1, push_enabled INTEGER DEFAULT 1, email_categories TEXT, sms_categories TEXT, do_not_disturb_start TEXT, do_not_disturb_end TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP ) """)

                # 创建索引
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_type ON notifications(type, category)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_status ON emails(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_to ON emails(to_address)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sms_status ON sms_messages(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sms_phone ON sms_messages(phone_number)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_conv ON chat_messages(conversation_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_sender ON chat_messages(sender_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_part ON chat_participants(user_id)")

                conn.commit()
                logger.info("通讯中心数据库表初始化完成")

    def _init_templates(self):
        """初始化默认模板"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as cnt FROM email_templates")
                if cursor.fetchone()['cnt'] > 0:
                    return

                # 邮件模板
                email_templates = [
                    {
                        'template_id': 'TPL-EMAIL-WELCOME',
                        'name': '欢迎注册',
                        'subject': '欢迎加入MTSCOS AI智能考试系统',
                        'body_text': '亲爱的{{username}}，\n\n欢迎您加入MTSCOS  AI智能考试系统！\n\n您的账号已成功创建，现在可以开始使用系统提供的各项功能。\n\n如有任何问题，请随时联系我们。\n\nMTSCOS AI团队',
                        'body_html': '<h2>欢迎加入MTSCOS AI</h2><p>亲爱的{{username}}，</p><p>欢迎您加入MTSCOS  AI智能考试系统！您的账号已成功创建。</p><p>MTSCOS AI团队</p>',
                        'category': 'system',
                        'variables': json.dumps(['username'])
                    },
                    {
                        'template_id': 'TPL-EMAIL-EXAM-REMINDER',
                        'name': '考试提醒',
                        'subject': '【考试提醒】{{exam_name}}即将开始',
                        'body_text': 
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        '亲爱的{{username}}，\n\n您报名的考试{{exam_name}}将于{{exam_time}}开始。\n\n考试时长：{{duration}}分钟\n考试地点：{{location}}\n\n请提前15分钟到达，祝您考试顺利！\n\nMTSCOS AI团队',
                        'body_html': 
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        '<h2>考试提醒</h2><p>亲爱的{{username}}，</p><p>您报名的考试<strong>{{exam_name}}</strong>将于{{exam_time}}开始。</p><p>考试时长：{{duration}}分钟</p><p>考试地点：{{location}}</p><p>请提前15分钟到达，祝您考试顺利！</p>',
                        'category': 'exam',
                        'variables': json.dumps(['username', 'exam_name', 'exam_time', 'duration', 'location'])
                    },
                    {
                        'template_id': 'TPL-EMAIL-SCORE',
                        'name': '成绩通知',
                        'subject': '【成绩通知】{{exam_name}}成绩已发布',
                        'body_text': 
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        '亲爱的{{username}}，\n\n您的{{exam_name}}成绩已发布。\n\n分数：{{score}}分\n等级：{{level}}\n\n请登录系统查看详细分析报告。\n\nMTSCOS AI团队',
                        'body_html': 
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        
                        '<h2>成绩通知</h2><p>亲爱的{{username}}，</p><p>您的<strong>{{exam_name}}</strong>成绩已发布。</p><p>分数：{{score}}分</p><p>等级：{{level}}</p><p>请登录系统查看详细分析报告。</p>',
                        'category': 'exam',
                        'variables': json.dumps(['username', 'exam_name', 'score', 'level'])
                    }
                ]

                for tpl in email_templates:
                    cursor.execute(""" INSERT OR IGNORE INTO email_templates (template_id, name, subject, body_text, body_html, category, variables) VALUES (?, ?, ?, ?, ?, ?, ?) """, (tpl['template_id'], tpl['name'], tpl['subject'],
                          tpl['body_text'], tpl['body_html'], tpl['category'], tpl['variables']))

                # 短信模板
                sms_templates = [
                    {
                        'template_id': 'TPL-SMS-VERIFY',
                        'name': '验证码',
                        'content': '【MTSCOS】您的验证码是{{code}}，有效期{{minutes}}分钟，请勿泄露给他人。',
                        'category': 'verification',
                        'variables': json.dumps(['code', 'minutes'])
                    },
                    {
                        'template_id': 'TPL-SMS-EXAM',
                        'name': '考试提醒',
                        'content': '【MTSCOS】提醒：{{exam_name}}将于{{exam_time}}开始，请准时参加。',
                        'category': 'exam',
                        'variables': json.dumps(['exam_name', 'exam_time'])
                    },
                    {
                        'template_id': 'TPL-SMS-SCORE',
                        'name': '成绩通知',
                        'content': '【MTSCOS】您的{{exam_name}}成绩已发布，分数：{{score}}分，请登录查看。',
                        'category': 'exam',
                        'variables': json.dumps(['exam_name', 'score'])
                    }
                ]

                for tpl in sms_templates:
                    cursor.execute(""" INSERT OR IGNORE INTO sms_templates (template_id, name, content, category, variables) VALUES (?, ?, ?, ?, ?) """, (tpl['template_id'], tpl['name'], tpl['content'], tpl['category'], tpl['variables']))

                conn.commit()
                logger.info("通讯模板初始化完成")

    # ==================== 站内通知 ====================

    def send_notification(self, user_id: int, title: str, content: str = '',
                          notif_type: str = 'info', category: str = 'system',
                          priority: str = 'normal', sender_id: int = None,
                          sender_name: str = '系统', action_url: str = None,
                          action_text: str = None, expires_at: str = None) -> Dict[str, Any]:
        """发送站内通知"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                notification_id = f"NOTIF-{uuid.uuid4().hex[:8].upper()}"
                try:
                    cursor.execute(""" INSERT INTO notifications (notification_id, user_id, title, content, type, category, priority, status, sender_id, sender_name, action_url, action_text, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'unread', ?, ?, ?, ?, ?) """, (notification_id, user_id, title, content, notif_type,
                          category, priority, sender_id, sender_name, action_url,
                          action_text, expires_at))
                    conn.commit()
                    return {'success': True, 'notification_id': notification_id, 'message': '通知发送成功'}
                except Exception as e:
                    return {'success': False, 'error': str(e)}

    def send_batch_notifications(self, user_ids: List[int], title: str, content: str = '',
                                 **kwargs) -> Dict[str, Any]:
        """批量发送通知"""
        success_count = 0
        for uid in user_ids:
            result = self.send_notification(uid, title, content, **kwargs)
            if result.get('success'):
                success_count += 1
        return {'success': True, 'total': len(user_ids), 'sent': success_count}

    def get_notifications(self, user_id: int, status: str = None, category: str = None,
                          limit: int = 50, offset: int = 0) -> List[Dict]:
        """获取用户通知列表"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT * FROM notifications WHERE user_id = ? AND archived = 0"
                params = [user_id]
                if status:
                    query += " AND status = ?"
                    params.append(status)
                if category:
                    query += " AND category = ?"
                    params.append(category)
                query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    def mark_notification_read(self, notification_id: str) -> Dict[str, Any]:
        """标记通知为已读"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE notifications SET status = 'read', read_at = ? WHERE notification_id = ?",
                    (datetime.now().isoformat(), notification_id)
                )
                conn.commit()
                return {'success': True, 'message': '已标记为已读'}

    def mark_all_read(self, user_id: int) -> Dict[str, Any]:
        """标记所有通知为已读"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE notifications SET status = 'read', read_at = ? WHERE user_id = ? AND status = 'unread'",
                    (datetime.now().isoformat(), user_id)
                )
                conn.commit()
                return {'success': True, 'updated': cursor.rowcount}

    def archive_notification(self, notification_id: str) -> Dict[str, Any]:
        """归档通知"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE notifications SET archived = 1 WHERE notification_id = ?",
                    (notification_id,)
                )
                conn.commit()
                return {'success': True, 'message': '已归档'}

    def delete_notification(self, notification_id: str) -> Dict[str, Any]:
        """删除通知"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM notifications WHERE notification_id = ?", (notification_id,))
                conn.commit()
                return {'success': True, 'message': '已删除'}

    def get_unread_count(self, user_id: int) -> int:
        """获取未读通知数"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT( *) as cnt FROM notifications WHERE user_id = ? AND status = 'unread' AND archived = 0",
                    (user_id,)
                )
                return cursor.fetchone()['cnt']

    # ==================== 邮件系统 ====================

    def send_email(self, to_address: str, subject: str, body_text: str = '',
                   body_html: str = None, template_id: str = None,
                   variables: Dict = None, cc_address: str = None,
                   priority: str = 'normal', created_by: int = None) -> Dict[str, Any]:
        """发送邮件（入队列）"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"

                # 使用模板
                if template_id:
                    cursor.execute("SELECT * FROM email_templates WHERE template_id = ?", (template_id,))
                    tpl = cursor.fetchone()
                    if tpl:
                        tpl = dict(tpl)
                        subject = tpl['subject']
                        body_text = tpl['body_text'] or ''
                        body_html = tpl['body_html']
                        if variables:
                            for key, val in variables.items():
                                subject = subject.replace(f'{{{{{key}}}}}', str(val))
                                body_text = body_text.replace(f'{{{{{key}}}}}', str(val))
                                if body_html:
                                    body_html = body_html.replace(f'{{{{{key}}}}}', str(val))

                from_address = os.environ.get('SMTP_FROM', 'noreply@mtscos.ai')

                try:
                    cursor.execute(""" INSERT INTO emails (email_id, from_address, to_address, cc_address, subject, body_text, body_html, template_id, status, priority, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?) """, (email_id, from_address, to_address, cc_address, subject,
                          body_text, body_html, template_id, priority, created_by))
                    conn.commit()

                    # 尝试实际发送
                    send_result = self._attempt_send_email(email_id)
                    return {'success': True, 'email_id': email_id,
                            'send_status': send_result.get('status', 'queued'),
                            'message': '邮件已加入发送队列'}
                except Exception as e:
                    return {'success': False, 'error': str(e)}

    def _attempt_send_email(self, email_id: str) -> Dict[str, Any]:
        """尝试发送邮件"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM emails WHERE email_id = ?", (email_id,))
                email = cursor.fetchone()
                if not email:
                    return {'status': 'not_found'}

                email = dict(email)
                smtp_host = os.environ.get('SMTP_HOST', '')
                smtp_port = int(os.environ.get('SMTP_PORT', '587'))
                smtp_user = os.environ.get('SMTP_USER', '')
                smtp_pass = os.environ.get('SMTP_PASS', '')

                # 如果没有配置SMTP，标记为模拟发送
                if not smtp_host:
                    cursor.execute(
                        "UPDATE emails SET status = 'simulated', sent_at = ? WHERE email_id = ?",
                        (datetime.now().isoformat(), email_id)
                    )
                    conn.commit()
                    return {'status': 'simulated', 'message': 'SMTP未配置，邮件标记为模拟发送'}

                # 实际发送
                try:
                    msg = MIMEMultipart('alternative')
                    msg['From'] = email['from_address']
                    msg['To'] = email['to_address']
                    msg['Subject'] = email['subject']
                    if email['cc_address']:
                        msg['Cc'] = email['cc_address']

                    msg.attach(MIMEText(email['body_text'], 'plain', 'utf-8'))
                    if email['body_html']:
                        msg.attach(MIMEText(email['body_html'], 'html', 'utf-8'))

                    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                        server.starttls()
                        server.login(smtp_user, smtp_pass)
                        server.send_message(msg)

                    cursor.execute(
                        "UPDATE emails SET status = 'sent', sent_at = ? WHERE email_id = ?",
                        (datetime.now().isoformat(), email_id)
                    )
                    conn.commit()
                    return {'status': 'sent', 'message': '邮件发送成功'}

                except Exception as e:
                    cursor.execute(
                        "UPDATE emails SET status = 'failed', error_message = ?, retry_count = retry_count + 1 WHERE email_id = ?",
                        (str(e)[:500], email_id)
                    )
                    conn.commit()
                    return {'status': 'failed', 'error': str(e)}

    def get_email_templates(self, category: str = None) -> List[Dict]:
        """获取邮件模板列表"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT * FROM email_templates WHERE is_active = 1"
                params = []
                if category:
                    query += " AND category = ?"
                    params.append(category)
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    def get_email_history(self, to_address: str = None, status: str = None,
                          limit: int = 50) -> List[Dict]:
        """获取邮件发送历史"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT * FROM emails WHERE 1=1"
                params = []
                if to_address:
                    query += " AND to_address = ?"
                    params.append(to_address)
                if status:
                    query += " AND status = ?"
                    params.append(status)
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    # ==================== 短信系统 ====================

    def send_sms(self, phone_number: str, content: str, template_id: str = None,
                 variables: Dict = None, sms_type: str = 'notification',
                 priority: str = 'normal', created_by: int = None) -> Dict[str, Any]:
        """发送短信"""
        # 验证手机号
        if not re.match(r'^1[3-9]\d{9}$', phone_number):
            return {'success': False, 'error': '手机号格式不正确'}

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                sms_id = f"SMS-{uuid.uuid4().hex[:8].upper()}"

                # 使用模板
                if template_id:
                    cursor.execute("SELECT * FROM sms_templates WHERE template_id = ?", (template_id,))
                    tpl = cursor.fetchone()
                    if tpl:
                        tpl = dict(tpl)
                        content = tpl['content']
                        if variables:
                            for key, val in variables.items():
                                content = content.replace(f'{{{{{key}}}}}', str(val))

                # 检查长度
                if len(content) > 500:
                    return {'success': False, 'error': '短信内容超过500字符'}

                try:
                    cursor.execute(""" INSERT INTO sms_messages (sms_id, phone_number, content, template_id, sms_type, status, priority, created_by) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?) """, (sms_id, phone_number, content, template_id, sms_type,
                          priority, created_by))
                    conn.commit()

                    # 模拟发送（实际环境对接短信服务商API）
                    cursor.execute(
                        "UPDATE sms_messages SET status = 'sent', sent_at = ?, provider_message_id = ? WHERE sms_id = ?",
                        (datetime.now().isoformat(), f"PROV-{uuid.uuid4().hex[:12]}", sms_id)
                    )
                    conn.commit()

                    return {'success': True, 'sms_id': sms_id, 'message': '短信发送成功'}
                except Exception as e:
                    return {'success': False, 'error': str(e)}

    def send_verification_code(self, phone_number: str, purpose: str = 'login') -> Dict[str, Any]:
        """发送验证码"""
        import random
        code = str(random.randint(100000, 999999))
        expires_at = (datetime.now() + timedelta(minutes=5)).isoformat()

        result = self.send_sms(
            phone_number=phone_number,
            content=f'',
            template_id='TPL-SMS-VERIFY',
            variables={'code': code, 'minutes': '5'},
            sms_type='verification'
        )

        if result.get('success'):
            with self._lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    code_id = f"CODE-{uuid.uuid4().hex[:8].upper()}"
                    cursor.execute(""" INSERT INTO sms_verification_codes (code_id, phone_number, code, purpose, expires_at) VALUES (?, ?, ?, ?, ?) """, (code_id, phone_number, code, purpose, expires_at))
                    conn.commit()
                    return {'success': True, 'code_id': code_id, 'message': '验证码已发送'}

        return result

    def verify_code(self, phone_number: str, code: str, purpose: str = 'login') -> Dict[str, Any]:
        """验证验证码"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(""" SELECT * FROM sms_verification_codes WHERE phone_number = ? AND code = ? AND purpose = ? AND used = 0 AND expires_at > ? ORDER BY created_at DESC LIMIT 1 """, (phone_number, code, purpose, datetime.now().isoformat()))
                record = cursor.fetchone()

                if record:
                    cursor.execute(
                        "UPDATE sms_verification_codes SET used = 1, used_at = ? WHERE code_id = ?",
                        (datetime.now().isoformat(), record['code_id'])
                    )
                    conn.commit()
                    return {'success': True, 'message': '验证成功'}
                else:
                    # 增加尝试次数
                    cursor.execute(""" UPDATE sms_verification_codes SET attempt_count = attempt_count + 1 WHERE phone_number = ? AND purpose = ? AND used = 0 """, (phone_number, purpose))
                    conn.commit()
                    return {'success': False, 'error': '验证码无效或已过期'}

    def get_sms_history(self, phone_number: str = None, status: str = None,
                        limit: int = 50) -> List[Dict]:
        """获取短信发送历史"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT * FROM sms_messages WHERE 1=1"
                params = []
                if phone_number:
                    query += " AND phone_number = ?"
                    params.append(phone_number)
                if status:
                    query += " AND status = ?"
                    params.append(status)
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    # ==================== 交流系统 ====================

    def create_conversation(self, creator_id: int, participant_ids: List[int],
                            conversation_type: str = 'direct', name: str = None) -> Dict[str, Any]:
        """创建会话"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                conversation_id = f"CONV-{uuid.uuid4().hex[:8].upper()}"

                all_participants = list(set([creator_id] + participant_ids))
                if conversation_type == 'direct' and len(all_participants) > 2:
                    conversation_type = 'group'
                if conversation_type == 'group' and not name:
                    name = f'群聊({len(all_participants)}人)'

                try:
                    cursor.execute(""" INSERT INTO chat_conversations (conversation_id, conversation_type, name, creator_id, participant_ids) VALUES (?, ?, ?, ?, ?) """, (conversation_id, conversation_type, name, creator_id,
                          json.dumps(all_participants)))

                    # 添加参与者
                    for uid in all_participants:
                        role = 'admin' if uid == creator_id else 'member'
                        cursor.execute(""" INSERT OR IGNORE INTO chat_participants (conversation_id, user_id, role) VALUES (?, ?, ?) """, (conversation_id, uid, role))

                    conn.commit()
                    return {'success': True, 'conversation_id': conversation_id,
                            'message': '会话创建成功'}
                except Exception as e:
                    return {'success': False, 'error': str(e)}

    def send_message(self, conversation_id: str, sender_id: int, content: str,
                     message_type: str = 'text', sender_name: str = None,
                     sender_avatar: str = None, attachment_url: str = None,
                     attachment_name: str = None, reply_to_id: str = None) -> Dict[str, Any]:
        """发送消息"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # 验证参与者
                cursor.execute(
                    "SELECT 1 FROM chat_participants WHERE conversation_id = ? AND user_id = ? AND is_active = 1",
                    (conversation_id, sender_id)
                )
                if not cursor.fetchone():
                    return {'success': False, 'error': '您不在此会话中'}

                message_id = f"MSG-{uuid.uuid4().hex[:8].upper()}"
                try:
                    cursor.execute(""" INSERT INTO chat_messages (message_id, conversation_id, sender_id, sender_name, sender_avatar, message_type, content, attachment_url, attachment_name, reply_to_id, read_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) """, (message_id, conversation_id, sender_id, sender_name, sender_avatar,
                          message_type, content, attachment_url, attachment_name,
                          reply_to_id, json.dumps([sender_id])))

                    # 更新会话最后消息
                    preview = content[:50] if content else (attachment_name or '[附件]')
                    cursor.execute(""" UPDATE chat_conversations SET last_message_id = ?, last_message_preview = ?, last_message_at = ?, updated_at = ? WHERE conversation_id = ? """, (message_id, preview, datetime.now().isoformat(),
                          datetime.now().isoformat(), conversation_id))

                    conn.commit()
                    return {'success': True, 'message_id': message_id, 'message': '消息发送成功'}
                except Exception as e:
                    return {'success': False, 'error': str(e)}

    def get_messages(self, conversation_id: str, user_id: int,
                     limit: int = 50, before_id: str = None) -> List[Dict]:
        """获取会话消息"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                query = """ SELECT * FROM chat_messages WHERE conversation_id = ? AND is_deleted = 0 """
                params = [conversation_id]

                if before_id:
                    cursor.execute("SELECT created_at FROM chat_messages WHERE message_id = ?", (before_id,))
                    before_row = cursor.fetchone()
                    if before_row:
                        query += " AND created_at < ?"
                        params.append(before_row['created_at'])

                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)
                messages = [dict(row) for row in cursor.fetchall()]

                # 标记为已读
                cursor.execute(""" UPDATE chat_participants SET last_read_at = ?, last_read_message_id = ? WHERE conversation_id = ? AND user_id = ? """, (datetime.now().isoformat(),
                      messages[0]['message_id'] if messages else None,
                      conversation_id, user_id))

                # 更新消息的read_by
                for msg in messages:
                    read_by = json.loads(msg.get('read_by') or '[]')
                    if user_id not in read_by:
                        read_by.append(user_id)
                        cursor.execute(
                            "UPDATE chat_messages SET read_by = ? WHERE message_id = ?",
                            (json.dumps(read_by), msg['message_id'])
                        )

                conn.commit()
                return list(reversed(messages))

    def get_conversations(self, user_id: int) -> List[Dict]:
        """获取用户会话列表"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(""" SELECT c.*, p.last_read_message_id, p.last_read_at, (SELECT COUNT(*) FROM chat_messages m WHERE m.conversation_id = c.conversation_id AND m.is_deleted = 0 AND (m.read_by IS NULL OR m.read_by NOT LIKE ?)) as unread FROM chat_conversations c JOIN chat_participants p ON c.conversation_id = p.conversation_id WHERE p.user_id = ? AND p.is_active = 1 AND c.status = 'active' ORDER BY c.is_pinned DESC, c.last_message_at DESC """, (f'%"{user_id}"%', user_id))
                convs = [dict(row) for row in cursor.fetchall()]

                # 获取参与者信息
                for conv in convs:
                    cursor.execute(""" SELECT user_id, role FROM chat_participants WHERE conversation_id = ? AND is_active = 1 """, (conv['conversation_id'],))
                    conv['participants'] = [dict(r) for r in cursor.fetchall()]

                return convs

    def delete_message(self, message_id: str, user_id: int) -> Dict[str, Any]:
        """删除消息（软删除）"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT sender_id FROM chat_messages WHERE message_id = ?",
                    (message_id,)
                )
                msg = cursor.fetchone()
                if not msg:
                    return {'success': False, 'error': '消息不存在'}
                if msg['sender_id'] != user_id:
                    return {'success': False, 'error': '只能删除自己的消息'}

                cursor.execute(
                    "UPDATE chat_messages SET is_deleted = 1, deleted_at = ? WHERE message_id = ?",
                    (datetime.now().isoformat(), message_id)
                )
                conn.commit()
                return {'success': True, 'message': '消息已删除'}

    # ==================== 通讯统计 ====================

    def get_stats(self) -> Dict[str, Any]:
        """获取通讯中心统计"""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT COUNT(*) as cnt FROM notifications WHERE status = 'unread'")
                unread_notifs = cursor.fetchone()['cnt']

                cursor.execute("SELECT COUNT(*) as cnt FROM notifications")
                total_notifs = cursor.fetchone()['cnt']

                cursor.execute("SELECT COUNT(*) as cnt FROM emails WHERE status = 'sent'")
                sent_emails = cursor.fetchone()['cnt']

                cursor.execute("SELECT COUNT(*) as cnt FROM emails WHERE status = 'pending'")
                pending_emails = cursor.fetchone()['cnt']

                cursor.execute("SELECT COUNT(*) as cnt FROM emails WHERE status = 'failed'")
                failed_emails = cursor.fetchone()['cnt']

                cursor.execute("SELECT COUNT(*) as cnt FROM sms_messages WHERE status = 'sent'")
                sent_sms = cursor.fetchone()['cnt']

                cursor.execute("SELECT COUNT(*) as cnt FROM chat_conversations WHERE status = 'active'")
                active_convs = cursor.fetchone()['cnt']

                cursor.execute("SELECT COUNT(*) as cnt FROM chat_messages WHERE is_deleted = 0")
                total_messages = cursor.fetchone()['cnt']

                cursor.execute("SELECT COUNT(*) as cnt FROM email_templates WHERE is_active = 1")
                email_templates = cursor.fetchone()['cnt']

                cursor.execute("SELECT COUNT(*) as cnt FROM sms_templates WHERE is_active = 1")
                sms_templates = cursor.fetchone()['cnt']

                return {
                    'notifications': {
                        'total': total_notifs,
                        'unread': unread_notifs
                    },
                    'emails': {
                        'sent': sent_emails,
                        'pending': pending_emails,
                        'failed': failed_emails
                    },
                    'sms': {
                        'sent': sent_sms
                    },
                    'chat': {
                        'active_conversations': active_convs,
                        'total_messages': total_messages
                    },
                    'templates': {
                        'email': email_templates,
                        'sms': sms_templates
                    }
                }


communication_service = CommunicationCenterService()
