"""
统一审批中台 (approval v2) — engines/approval/
==============================================
模块划分:
  db.py            短连接/重试/幂等 schema 迁移
  policy.py        风险规则/角色链/SLA/LLM 矩阵 唯一配置源
  chains.py        风险评估 + 审批链构建 (会签/或签/指定人/VIKEY)
  authz.py         动作鉴权矩阵
  state_machine.py 单事务状态流转 + 会签计票
  service.py       ApprovalService 全部业务方法
  reconcile.py     存量陈旧单处置
  llm_review.py    本地 Ollama 语义预审 (P3)
  callbacks.py     业务回调字符串注册表 (P4)
  tick.py          daemon 五阶段 (P3)

兼容: engines/approvals_engine.py 是本包的薄 shim, 旧调用点零改动。
"""
from .db import DB_PATH, ensure_schema, get_conn  # noqa: F401
from .policy import assess_risk, ROLE_CHAIN  # noqa: F401
from .chains import build_nodes, backfill_chain  # noqa: F401
from .service import ApprovalService  # noqa: F401

__all__ = [
    'DB_PATH', 'ensure_schema', 'get_conn',
    'assess_risk', 'ROLE_CHAIN', 'build_nodes', 'backfill_chain',
    'ApprovalService',
]
