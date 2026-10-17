# -*- coding: utf-8 -*-
"""rule_approval stub - 规则审批服务兼容层 (flow_id=fix_rules_500_20260902)

原模块缺失, 创建 stub 避免 /_rules/proposals 等 API 500.
提供最小化接口, 返回空数据.
"""
import sqlite3, os, time
from typing import List, Dict, Any, Optional

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'ai_engines', 'app.db')

PROPOSAL_STATUSES = ('draft', 'pending_review', 'approved', 'rejected', 'withdrawn', 'implemented')


def _get_conn():
    return sqlite3.connect(_DB_PATH, timeout=10) if os.path.exists(_DB_PATH) else None


def list_my_proposals(username: str = '', limit: int = 100) -> List[Dict[str, Any]]:
    return []


def list_pending_approvals(username: str = '', limit: int = 100, **kwargs) -> List[Dict[str, Any]]:
    return []


def create_proposal(title: str = '', content: str = '', proposer: str = '', rule_path: str = '', rule_type: str = 'config') -> Dict[str, Any]:
    return {'success': False, 'message': 'rule_approval stub: 创建提案功能未实现', 'proposal_id': None}


def approve_proposal(proposal_id: int, approver: str = '', comment: str = '') -> Dict[str, Any]:
    return {'success': False, 'message': 'rule_approval stub: 审批通过功能未实现'}


def reject_proposal(proposal_id: int, approver: str = '', comment: str = '') -> Dict[str, Any]:
    return {'success': False, 'message': 'rule_approval stub: 驳回功能未实现'}


def get_proposal(proposal_id: int) -> Optional[Dict[str, Any]]:
    return None


def ai_firewall_review(proposal_id: int) -> Dict[str, Any]:
    return {'success': True, 'risk_level': 'low', 'comment': 'rule_approval stub: 自动放行', 'allow': True}


def super_admin_approval(proposal_id: int, approver: str = '', comment: str = '') -> Dict[str, Any]:
    return {'success': False, 'message': 'rule_approval stub: SA审批功能未实现'}


def withdraw_proposal(proposal_id: int, username: str = '') -> Dict[str, Any]:
    return {'success': False, 'message': 'rule_approval stub: 撤回功能未实现'}
