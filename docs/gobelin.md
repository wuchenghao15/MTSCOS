# 古灵阁 Gobelin 系统说明

> 自动生成时间: 2026-11-12 06:39
> 系统哈希: 457b124c26679134... (变更时更新)
> 源码路径: engines/gobelin_daily_pnl.py, engines/gobelin_adapter.py, engines/gobelin_guardian.py, engines/gobelin_scheduler.py, engines/gobelin_community_fusion.py

## 1. 系统概述
<!-- AUTO-GENERATED-START:overview -->
🛡️ 金盾系统蓝图 v2.0 (flow_gobelin_shield_20261104)
=====================================================
古灵阁集团 · 29 安全维度统一审计 + 海关总署 + 协同总线 + 仙女座/冰山/ComfyUI 全适配

━━━ 29 安全维度 ━━━
  #   维度 key                   中文名                    检查目标
  ───────────────────────────────────────────────────────────────────
  S1   financial_security        金融安全                  转账/锁利/资金池
  S2   legal_security            法

**模块数**: 39 | **类**: 28 | **顶层函数**: 746
<!-- AUTO-GENERATED-END:overview -->

## 2. 架构图 (ASCII)
<!-- AUTO-GENERATED-START:arch -->
  ╔══════════════════════════════════════════════════════════╗
  ║  古灵阁 Gobelin                                     ║
  ╠══════════════════════════════════════════════════════════╣
  ║                                                          ║
  ║  ┌─ 入口 API ──────────────────────────────────────────┐  ║
  ║  │  ANY /account                                          │  ║
  ║  │  ANY /decisions                                        │  ║
  ║  │  ANY /events                                           │  ║
  ║  │  ANY /kline                                            │  ║
  ║  │  ANY /positions                                        │  ║
  ║  └─────────────────────────────────────────────────────┘  ║
  ║                          │                               ║
  ║                          ▼                               ║
  ║  ┌─ 核心引擎 ──────────────────────────────────────────┐  ║
  ║  │  GobelinDailyPnl                                       │  ║
  ║  │  ActorPool                                             │  ║
  ║  │  ScenarioEngine                                        │  ║
  ║  │  ActorAgent                                            │  ║
  ║  │  MultiTurnDiscussionEngine                             │  ║
  ║  └─────────────────────────────────────────────────────┘  ║
  ║                          │                               ║
  ║                          ▼                               ║
  ║  ┌─ 数据库表 ──────────────────────────────────────────┐  ║
  ║  │  mt_community_gobelin_roles                            │  ║
  ║  │  mt_gobelin_account                                    │  ║
  ║  │  mt_gobelin_account_archive                            │  ║
  ║  │  mt_gobelin_archive                                    │  ║
  ║  │  mt_gobelin_meeting_log                                │  ║
  ║  │  mt_gobelin_music_project                              │  ║
  ║  └─────────────────────────────────────────────────────┘  ║
  ║                                                          ║
  ╚══════════════════════════════════════════════════════════╝
<!-- AUTO-GENERATED-END:arch -->

## 3. API 端点
<!-- AUTO-GENERATED-START:api -->
| 蓝图 | 方法 | URL | 处理函数 | 说明 |
|------|------|-----|----------|------|
| gobelin_bp | ANY | /account | account_refresh | 刷新所有持仓价格 + 汇总账户 PnL (用真实行情) |
| gobelin_bp | ANY | /account/refresh | account_refresh | 刷新所有持仓价格 + 汇总账户 PnL (用真实行情) |
| gobelin_bp | ANY | /api/gobelin/daemons | gobelin_daemons | 快速 daemons 列表 |
| gobelin_bp | ANY | /api/gobelin/status | gobelin_status | 古灵阁总状态 — 聚合所有子系统 |
| gobelin_bp | ANY | /api/gobelin/status-v2 | api_gobelin_status_v |  |
| gobelin_bp | ANY | /api/gobelin/subsystem/<key> | api_gobelin_subsyste |  |
| gobelin_bp | ANY | /api/gobelin/system | api_gobelin_system |  |
| gobelin_bp | ANY | /autonomous/cycle | autonomous_cycle | 完整自动投资 cycle (行情→提案→议会→发章→执行) |
| gobelin_bp | ANY | /autonomous/execute | autonomous_execute | 只执行已发章的交易 |
| gobelin_bp | ANY | /autonomous/report | autonomous_report |  |
| gobelin_bp | ANY | /autonomous/scan | autonomous_scan |  |
| gobelin_bp | ANY | /collab/analyze/<int:proposal_id> | collab_analyze | 触发提案智能分析 |
| gobelin_bp | ANY | /collab/dispatch/<int:proposal_id> | collab_dispatch | 触发派单 |
| gobelin_bp | ANY | /collab/growth | collab_growth | AI 成长追踪 |
| gobelin_bp | ANY | /collab/minutes/<int:plan_id> | collab_minutes | 协作纪要 Markdown |
| gobelin_bp | ANY | /collab/proposal/<int:proposal_id> | collab_proposal | 查看提案协作方案 + 痕迹 + 纪要 |
| gobelin_bp | ANY | /collab/run-pending | collab_run_pending | 批量处理 PENDING 提案 |
| gobelin_bp | ANY | /collab/traces | collab_traces | 最近 50 条协作痕迹 |
| gobelin_bp | ANY | /community/bootstrap | community_bootstrap | 触发社区一键初始化 |
| gobelin_bp | ANY | /community/calibrations | community_calibratio | 反推校正记录 (最近 50 条) |
| gobelin_bp | ANY | /community/employees | community_employees | Gobelin Bank AI 员工列表 (含师徒/岗位/能力) |
| gobelin_bp | ANY | /community/health | community_health | AI 社区全景健康体检 |
| gobelin_bp | ANY | /community/roles | community_roles | Gobelin Bank 岗位图谱 |
| gobelin_bp | ANY | /community/training | community_training | 培训进度 (最近 50 条) |
| gobelin_bp | ANY | /compliance | compliance_audit | 合规审计详情 |
| gobelin_bp | ANY | /dashboard | dashboard_snapshot | Gobelin 仪表盘 JSON 快照 — adapter 统一取价 (v2,  |
| gobelin_bp | ANY | /health | health |  |
| gobelin_bp | ANY | /parliament/proposal/<int:proposal_id> | parliament_proposal |  |
| gobelin_bp | ANY | /parliament/session/<int:session_id> | parliament_session |  |
| gobelin_bp | ANY | /parliament/vote-all | parliament_vote_all |  |
| gobelin_bp | ANY | /parliament/vote/<int:proposal_id> | parliament_vote |  |
| gobelin_bp | ANY | /positions | positions_list | 持仓列表 (带真实 PnL) |
| gobelin_bp | ANY | /proposal/create | proposal_create |  |
| gobelin_bp | ANY | /proposals | proposals_list |  |
| gobelin_bp | ANY | /scheduler | scheduler_status | 调度器运行状态 |
| gobelin_bp | ANY | /seal/<int:proposal_id> | seal_by_proposal |  |
| gobelin_bp | ANY | /seal/audit | seal_audit |  |
| gobelin_bp | ANY | /seal/auto-grant | seal_auto_grant |  |
| gobelin_bp | ANY | /seal/consume | seal_consume |  |
| gobelin_bp | ANY | /seal/request | seal_request |  |
| gobelin_bp | ANY | /seal/status | seal_status |  |
| gobelin_bp | ANY | /seal/verify | seal_verify |  |
| gobelin_bp | ANY | /trades | trades_list | 交易流水 (Gobelin Bank 真实成交) |
| gobelin_bp | ANY | /view | gobelin_view | HTML 仪表盘 (浏览器直接看) |
| gobelin_musi | ANY | /<int:pid> | get_project |  |
| gobelin_musi | ANY | /generate | generate | 完整歌曲生成 |
| gobelin_musi | ANY | /genres | list_genres |  |
| gobelin_musi | ANY | /health | health |  |
| gobelin_musi | ANY | /projects | list_projects |  |
| gobelin_vide | ANY | /<int:pid> | get_project |  |
| gobelin_vide | ANY | /<int:pid>/shots.json | export_shots | 导出分镜为 JSON, 供 AI 视频生成管线使用 |
| gobelin_vide | ANY | /formats | list_formats |  |
| gobelin_vide | ANY | /generate | generate | 完整视频脚本生成: 创意 → 分镜 → 配音 |
| gobelin_vide | ANY | /health | health |  |
| gobelin_vide | ANY | /projects | list_projects |  |
| gobelin_writ | ANY | /<int:pid> | api_writing_revise | 迭代改写: 扩写 / 缩写 / 改风格 / 续写 — 代理到 copy_stud |
| gobelin_writ | ANY | /<int:pid>/export/<fmt> | api_writing_export | 导出格式: txt / md / json — copy_studio 优先,  |
| gobelin_writ | ANY | /<int:pid>/revise | api_writing_revise | 迭代改写: 扩写 / 缩写 / 改风格 / 续写 — 代理到 copy_stud |
| gobelin_writ | ANY | /create | api_writing_create | v26.12 整合版 — 代理到 copy_studio engine.quic |
| gobelin_writ | ANY | /generate | api_writing_generate | v26.12 整合版 — 兼容 writing_server.py 风格, 代理 |
| gobelin_writ | ANY | /genres | api_writing_genres | 兼容 writing_server.py /api/writing/genres |
| gobelin_writ | ANY | /models | api_writing_models | 兼容 writing_server.py /api/writing/models |
| gobelin_writ | ANY | /params | api_writing_params | 返回所有创作参数枚举 — 前端创作台用 |
| gobelin_writ | ANY | /projects | api_writing_projects | 我的创作项目列表 — copy_studio mt_copy_projects  |
| sandbox_bp | ANY | /account | api_account | 账户状态 — 本金/现金/持仓市值/总资产/盈亏/手续费 |
| sandbox_bp | ANY | /ai-agents | api_ai_agents | 🧜 仙女座 AI 指挥中枢 — 返回所有 AI 员工实时状态 |
| sandbox_bp | ANY | /ai-dispatch | api_ai_dispatch | 🧜 仙女座指令派发 — 给 AI 员工派任务 |
| sandbox_bp | ANY | /audit/close-task | api_audit_close_task | 关闭审计任务 (复盘完成) |
| sandbox_bp | ANY | /audit/ledger | api_audit_ledger | 每笔进出账核对明细 (CPA 核账视角) |
| sandbox_bp | ANY | /audit/logs | api_audit_logs | 审计日志历史 (默认最新 20 条) |
| sandbox_bp | ANY | /audit/run | api_audit_run | 🏛️ 即时触发全量金融合规审计 (CFO+精算师+CPA+审计师) |
| sandbox_bp | ANY | /audit/task-hall | api_audit_task_hall | 审计异常触发的任务大厅 |
| sandbox_bp | ANY | /bank-withdraw | api_bank_withdraw | 🏦 存银行卡（真提现）— 必须经过金融团队开会表决          红线：提现 |
| sandbox_bp | ANY | /bank-withdrawals | api_bank_withdrawals | 🏦 银行存款流水历史 |
| sandbox_bp | ANY | /board-decide-sell | api_board_decide_sel | 收市 AI 军团研判卖哪些持仓 |
| sandbox_bp | ANY | /board-lock-profits | api_board_lock_profi | 🏛️ 董事会锁利研判 + 执行 — AI 军团自动开会投票 |
| sandbox_bp | ANY | /data/anomalies | api_data_anomalies | 数据异常列表 (支持 limit / severity / type / res |
| sandbox_bp | ANY | /data/health | api_data_health | 数据健康总览 — 各 DB 表行数 + 最新时间 + 过期状态 |
| sandbox_bp | ANY | /decisions | api_decisions | 决策流水 — 从 JSONL 文件读最新 N 条 |
| sandbox_bp | ANY | /deposit-gobelin | api_deposit_gobelin | Deposit to Gobelin bank card - verify re |

_（共 154 个端点,仅展示前 80 个）_
<!-- AUTO-GENERATED-END:api -->

## 4. 数据库表
<!-- AUTO-GENERATED-START:tables -->
### mt_community_gobelin_roles (21 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| role_code | TEXT |  | 否 |
| role_name | TEXT |  | 否 |
| center | TEXT |  | 是 |
| tier | TEXT |  | 是 |
| key_skills | TEXT |  | 是 |
| permissions | TEXT |  | 是 |
| mentor_required | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_gobelin_account (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| account_name | TEXT |  | 是 |
| total_assets | REAL |  | 是 |
| cash_balance | REAL |  | 是 |
| frozen_cash | REAL |  | 是 |
| position_value | REAL |  | 是 |
| realized_pnl | REAL |  | 是 |
| unrealized_pnl | REAL |  | 是 |
| total_deposit | REAL |  | 是 |
| total_withdraw | REAL |  | 是 |
| trade_count | INTEGER |  | 是 |
| initial_endowment | REAL |  | 是 |
| data_scope | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_gobelin_account_archive (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INT |  | 是 |
| account_name | TEXT |  | 是 |
| total_assets | REAL |  | 是 |
| cash_balance | REAL |  | 是 |
| frozen_cash | REAL |  | 是 |
| position_value | REAL |  | 是 |
| realized_pnl | REAL |  | 是 |
| unrealized_pnl | REAL |  | 是 |
| total_deposit | REAL |  | 是 |
| total_withdraw | REAL |  | 是 |
| trade_count | INT |  | 是 |
| initial_endowment | REAL |  | 是 |
| data_scope | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |
| archived_at | TEXT |  | 是 |

### mt_gobelin_archive (7 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INT |  | 是 |
| channel | TEXT |  | 是 |
| asset_code | TEXT |  | 是 |
| asset_name | TEXT |  | 是 |
| qty | REAL |  | 是 |
| available_qty | REAL |  | 是 |
| locked_qty | REAL |  | 是 |
| avg_cost_basis | REAL |  | 是 |
| total_cost | REAL |  | 是 |
| current_price | REAL |  | 是 |
| market_value | REAL |  | 是 |
| unrealized_pnl | REAL |  | 是 |
| unrealized_pnl_pct | REAL |  | 是 |
| today_pnl | REAL |  | 是 |
| prev_close | REAL |  | 是 |
| open_date | TEXT |  | 是 |
| last_trade_date | TEXT |  | 是 |
| data_scope | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_gobelin_meeting_log (45 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| meeting_code | TEXT |  | 是 |
| meeting_name | TEXT |  | 是 |
| trigger_time | TEXT |  | 是 |
| weekday | INTEGER |  | 是 |
| agenda_json | TEXT |  | 是 |
| result_json | TEXT |  | 是 |
| status | TEXT |  | 是 |
| data_scope | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_gobelin_music_project (2 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| title | TEXT |  | 是 |
| core_idea | TEXT |  | 是 |
| genre | TEXT |  | 是 |
| mood | TEXT |  | 是 |
| structure_key | TEXT |  | 是 |
| bpm | INTEGER |  | 是 |
| key_sig | TEXT |  | 是 |
| vocal_style | TEXT |  | 是 |
| instruments | TEXT |  | 是 |
| lyrics | TEXT |  | 是 |
| melody_outline | TEXT |  | 是 |
| arrangement | TEXT |  | 是 |
| ai_prompt | TEXT |  | 是 |
| model_used | TEXT |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_gobelin_music_section (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| project_id | INTEGER |  | 是 |
| section_order | INTEGER |  | 是 |
| section_name | TEXT |  | 是 |
| lyrics | TEXT |  | 是 |
| melody_hint | TEXT |  | 是 |
| chord_prog | TEXT |  | 是 |
| duration_sec | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |
**外键:**
| 本地列 | → 目标表 | 目标列 |
|--------|---------|--------|
| project_id | mt_gobelin_music_project | id |

### mt_gobelin_position (4 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| channel | TEXT |  | 否 |
| asset_code | TEXT |  | 否 |
| asset_name | TEXT |  | 否 |
| qty | REAL |  | 是 |
| available_qty | REAL |  | 是 |
| locked_qty | REAL |  | 是 |
| avg_cost_basis | REAL |  | 是 |
| total_cost | REAL |  | 是 |
| current_price | REAL |  | 是 |
| market_value | REAL |  | 是 |
| unrealized_pnl | REAL |  | 是 |
| unrealized_pnl_pct | REAL |  | 是 |
| today_pnl | REAL |  | 是 |
| prev_close | REAL |  | 是 |
| open_date | TEXT |  | 是 |
| last_trade_date | TEXT |  | 是 |
| data_scope | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_gobelin_price (4 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| channel | TEXT |  | 否 |
| asset_code | TEXT |  | 否 |
| asset_name | TEXT |  | 是 |
| last_price | REAL |  | 是 |
| prev_close | REAL |  | 是 |
| chg_pct | REAL |  | 是 |
| source | TEXT |  | 是 |
| data_scope | TEXT |  | 是 |
| fetched_at | TEXT |  | 是 |

### mt_gobelin_reflect_log (25 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| reflect_type | TEXT |  | 是 |
| subject | TEXT |  | 是 |
| root_cause | TEXT |  | 是 |
| fix_applied | TEXT |  | 是 |
| lessons | TEXT |  | 是 |
| related_tables | TEXT |  | 是 |
| confidence | REAL |  | 是 |
| consumed | INTEGER |  | 是 |
| data_scope | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_gobelin_savings (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| lock_date | TEXT |  | 否 |
| amount | REAL |  | 否 |
| reason | TEXT |  | 是 |
| board_vote | TEXT |  | 是 |
| new_total | REAL |  | 是 |
| created_at | TEXT |  | 是 |

### mt_gobelin_scheduler_heartbeat (326 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| heartbeat_time | TEXT |  | 是 |
| current_meeting | TEXT |  | 是 |
| next_meeting | TEXT |  | 是 |
| active_channels | TEXT |  | 是 |
| scheduler_version | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_gobelin_summary (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| total_savings | REAL |  | 是 |
| lock_count | INTEGER |  | 是 |
| last_lock_date | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_gobelin_trade (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| trade_id | TEXT |  | 否 |
| proposal_id | INTEGER |  | 是 |
| channel | TEXT |  | 否 |
| asset_code | TEXT |  | 否 |
| asset_name | TEXT |  | 否 |
| ptype | TEXT |  | 否 |
| qty | REAL |  | 否 |
| exec_price | REAL |  | 否 |
| avg_cost_before | REAL |  | 是 |
| avg_cost_after | REAL |  | 是 |
| amount | REAL |  | 否 |
| commission | REAL |  | 是 |
| stamp_tax | REAL |  | 是 |
| total_fee | REAL |  | 是 |
| cash_impact | REAL |  | 是 |
| realized_pnl | REAL |  | 是 |
| seal_code | TEXT |  | 是 |
| seal_token_hash | TEXT |  | 是 |
| status | TEXT |  | 是 |

### mt_gobelin_video_project (4 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| title | TEXT |  | 是 |
| core_idea | TEXT |  | 是 |
| format_key | TEXT |  | 是 |
| format_label | TEXT |  | 是 |
| style | TEXT |  | 是 |
| emotion | TEXT |  | 是 |
| target_dur | INTEGER |  | 是 |
| model_used | TEXT |  | 是 |
| status | TEXT |  | 是 |
| shot_list | TEXT |  | 是 |
| voiceover | TEXT |  | 是 |
| bgm_mood | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_gobelin_video_shot (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| project_id | INTEGER |  | 是 |
| shot_no | INTEGER |  | 是 |
| duration_sec | REAL |  | 是 |
| camera_angle | TEXT |  | 是 |
| movement | TEXT |  | 是 |
| subject_prompt | TEXT |  | 是 |
| visual_desc | TEXT |  | 是 |
| audio_prompt | TEXT |  | 是 |
| subtitle | TEXT |  | 是 |
| sfx_hint | TEXT |  | 是 |
| transition_in | TEXT |  | 是 |
| transition_out | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
**外键:**
| 本地列 | → 目标表 | 目标列 |
|--------|---------|--------|
| project_id | mt_gobelin_video_project | id |

### mt_sandbox_history (16 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| cache_key | TEXT | ✓ | 是 |
| secid | TEXT |  | 否 |
| start_date | TEXT |  | 否 |
| end_date | TEXT |  | 否 |
| data_json | TEXT |  | 否 |
| source | TEXT |  | 否 |
| fetched_at | TEXT |  | 否 |
| row_count | INTEGER |  | 否 |

### mt_sandbox_meetings (379 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| meeting_id | TEXT |  | 否 |
| meeting_type | TEXT |  | 否 |
| meeting_title | TEXT |  | 否 |
| host_node | TEXT |  | 是 |
| guest_nodes | TEXT |  | 是 |
| agenda | TEXT |  | 是 |
| conclusions | TEXT |  | 是 |
| decisions | TEXT |  | 是 |
| triggered_at | TEXT |  | 是 |
| started_at | TEXT |  | 是 |
| ended_at | TEXT |  | 是 |
| duration_min | REAL |  | 是 |
| status | TEXT |  | 是 |
| verifier | TEXT |  | 是 |
| version | INTEGER |  | 是 |
| participants | TEXT |  | 是 |
| actions | TEXT |  | 是 |
| evening_seq | INTEGER |  | 是 |
| afternoon_seq | INTEGER |  | 是 |

### mt_sandbox_portfolio (31 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| session_id | TEXT | ✓ | 是 |
| scenario | TEXT |  | 否 |
| scenario_days | INTEGER |  | 否 |
| initial_cash | REAL |  | 否 |
| current_cash | REAL |  | 否 |
| positions_json | TEXT |  | 是 |
| risk_floor_pct | REAL |  | 是 |
| daily_risk_pct | REAL |  | 是 |
| daily_high_watermark | REAL |  | 是 |
| is_frozen | INTEGER |  | 是 |
| status | TEXT |  | 是 |
| start_date | TEXT |  | 否 |
| current_date | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_sandbox_portfolio_bak_20261107 (30 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| session_id | TEXT |  | 是 |
| scenario | TEXT |  | 是 |
| scenario_days | INT |  | 是 |
| initial_cash | REAL |  | 是 |
| current_cash | REAL |  | 是 |
| positions_json | TEXT |  | 是 |
| risk_floor_pct | REAL |  | 是 |
| daily_risk_pct | REAL |  | 是 |
| daily_high_watermark | REAL |  | 是 |
| is_frozen | INT |  | 是 |
| status | TEXT |  | 是 |
| start_date | TEXT |  | 是 |
| current_date | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_sandbox_signals (948 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| signal_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| signal_date | TEXT |  | 否 |
| symbol | TEXT |  | 否 |
| stock_name | TEXT |  | 否 |
| signal_type | TEXT |  | 否 |
| strategy | TEXT |  | 否 |
| score | REAL |  | 否 |
| reason | TEXT |  | 是 |
| payload | TEXT |  | 是 |
| team_voted | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_sandbox_snapshots (150 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| snap_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| snap_date | TEXT |  | 否 |
| total_value | REAL |  | 否 |
| cash_value | REAL |  | 否 |
| position_value | REAL |  | 否 |
| daily_return | REAL |  | 是 |
| cumulative_return | REAL |  | 是 |
| max_drawdown | REAL |  | 是 |
| trade_count | INTEGER |  | 是 |
| notes | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| pnl_amount | REAL |  | 是 |

### mt_sandbox_team_verdicts (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| verdict_id | TEXT | ✓ | 是 |
| signal_id | TEXT |  | 否 |
| session_id | TEXT |  | 否 |
| expert_id | TEXT |  | 否 |
| expert_role | TEXT |  | 否 |
| verdict | TEXT |  | 否 |
| confidence | REAL |  | 是 |
| reasoning | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_sandbox_trades (63 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| trade_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| trade_date | TEXT |  | 否 |
| trade_time | TEXT |  | 否 |
| symbol | TEXT |  | 否 |
| stock_name | TEXT |  | 否 |
| action | TEXT |  | 否 |
| shares | INTEGER |  | 否 |
| price | REAL |  | 否 |
| commission | REAL |  | 是 |
| stamp_tax | REAL |  | 是 |
| total_amount | REAL |  | 否 |
| strategy | TEXT |  | 是 |
| signal_score | REAL |  | 是 |
| team_verdict | TEXT |  | 是 |
| risk_ok | INTEGER |  | 是 |
| source | TEXT |  | 是 |
| hall_task_id | TEXT |  | 是 |
| notes | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_shield_audit_log (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| action | TEXT |  | 否 |
| actor | TEXT |  | 否 |
| target | TEXT |  | 是 |
| result | TEXT |  | 是 |
| detail | TEXT |  | 是 |
| dimension | TEXT |  | 是 |
| risk_score | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_shield_comfy_jobs (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| job_id | TEXT |  | 是 |
| prompt | TEXT |  | 是 |
| workflow | TEXT |  | 是 |
| model_name | TEXT |  | 是 |
| status | TEXT |  | 是 |
| result_path | TEXT |  | 是 |
| created_by | TEXT |  | 是 |
| audited | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_shield_dimension_log (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| dim_code | TEXT |  | 否 |
| dim_key | TEXT |  | 否 |
| dim_name | TEXT |  | 否 |
| status | TEXT |  | 否 |
| risk_score | INTEGER |  | 是 |
| findings | TEXT |  | 是 |
| remediation | TEXT |  | 是 |
| scanned_at | TEXT |  | 是 |

### mt_shield_events (79,037 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| event_type | TEXT |  | 否 |
| source_force | TEXT |  | 否 |
| target_force | TEXT |  | 是 |
| payload | TEXT |  | 是 |
| severity | TEXT |  | 是 |
| hall_dispatched | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_shield_force_status (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| force_key | TEXT | ✓ | 是 |
| force_name | TEXT |  | 是 |
| status | TEXT |  | 是 |
| last_publish | TEXT |  | 是 |
| event_count | INTEGER |  | 是 |
| collab_bus_connected | INTEGER |  | 是 |
| iceberg_hall_connected | INTEGER |  | 是 |
| andromeda_connected | INTEGER |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_team_members (490 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| team_name | TEXT |  | 是 |
| member_name | TEXT |  | 是 |
| skill_level | TEXT |  | 是 |
| source | TEXT |  | 是 |
| capabilities | TEXT |  | 是 |
| member_id | TEXT |  | 是 |
| team_score_json | TEXT |  | 是 |
| assigned_at | TEXT |  | 是 |

### mt_team_registry (95 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| team_id | TEXT | ✓ | 是 |
| team_name | TEXT |  | 是 |
| member_count | INTEGER |  | 是 |
| skill_keywords | TEXT |  | 是 |
| color_tag | TEXT |  | 是 |
| auto_formed_at | TEXT |  | 是 |

### mt_ts_team (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| team_id | TEXT | ✓ | 是 |
| title | TEXT |  | 否 |
| description | TEXT |  | 是 |
| subject | TEXT |  | 是 |
| grade | TEXT |  | 是 |
| type | TEXT |  | 是 |
| status | TEXT |  | 是 |
| focus | TEXT |  | 是 |
| created_by | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |
<!-- AUTO-GENERATED-END:tables -->

## 5. 引擎函数清单
<!-- AUTO-GENERATED-START:functions -->
| 文件 | 类/函数 | 类型 | 参数 | 说明 |
|------|---------|------|------|------|
| sandbox_bp.py | def _cached_realtime | 函数 |  | 带缓存的 _load_realtime() — 30s 内重复调用直接返回 |
| sandbox_bp.py | def _get_db | 函数 |  |  |
| sandbox_bp.py | def api_account | 函数 |  | 账户状态 — 快速聚合(不调 broker 适配器,避免 5s 超时) |
| sandbox_bp.py | def api_positions | 函数 |  | 当前持仓 — 带实时行情 |
| sandbox_bp.py | def api_trades | 函数 |  | 今日交易流水 (mt_trade_log) — 带 realized_pnl 自 |
| sandbox_bp.py | def api_decisions | 函数 |  | 决策流水 — 从 JSONL 文件读最新 N 条 |
| sandbox_bp.py | def api_trades_jsonl | 函数 |  | 交易复盘日志 (含自动生成的经验教训) |
| sandbox_bp.py | def api_radar | 函数 |  | 实时行情 + 异动汇总 |
| sandbox_bp.py | def api_events | 函数 |  | 实时事件 — 从协作总线读今日事件, 去重清洗后返回 |
| sandbox_bp.py | def _sina_daily_kline | 函数 | secid, days | 新浪日线 K 线 — 给 MDS 没有的自选股补数据
secid: sh6000 |
| sandbox_bp.py | def api_kline | 函数 |  | K线数据 — 大盘 + 自选池
?symbol=000001 只返回上证
?da |
| sandbox_bp.py | def api_status | 函数 |  | 系统状态 — daemon + Flask + DB + heartbeat ( |
| sandbox_bp.py | def api_review | 函数 |  | 今日复盘 — 从协作总线 + SQLite 复盘会话表取 (含 5 层会议详情) |
| sandbox_bp.py | def api_trigger_review | 函数 |  | 手动触发复盘 — review_type: 'noon' / 'close' / |
| sandbox_bp.py | def api_ai_agents | 函数 |  | 🧜 仙女座 AI 指挥中枢 — 返回所有 AI 员工实时状态 |
| sandbox_bp.py | def api_ai_dispatch | 函数 |  | 🧜 仙女座指令派发 — 给 AI 员工派任务 |
| sandbox_bp.py | def _run_eng_review | 函数 | review_type | 隔离 wrapper — 避免 Flask 主路由内调用阻塞 |
| sandbox_bp.py | def _ensure_gobelin | 函数 |  | 确保古灵阁表存在 + summary 首行 |
| sandbox_bp.py | def _gobelin_read | 函数 |  | 读古灵阁当前余额 |
| sandbox_bp.py | def _gobelin_lock | 函数 | amount, reason, board_vote | 执行锁利 — 写入 savings 记录 + 更新 summary |
| sandbox_bp.py | def api_gobelin | 函数 |  | 🏛️ 古灵阁账户详情 — 累计锁利 / 历史记录 |
| sandbox_bp.py | def api_board_lock_profits | 函数 |  | 🏛️ 董事会锁利研判 + 执行 — AI 军团自动开会投票 |
| sandbox_bp.py | def api_board_decide_sell | 函数 |  | 收市 AI 军团研判卖哪些持仓 |
| sandbox_bp.py | def api_execute_sell | 函数 |  | Execute real sell - changes cash + posit |
| sandbox_bp.py | def api_deposit_gobelin | 函数 |  | Deposit to Gobelin bank card - verify re |
| sandbox_bp.py | def register_sandbox_bp | 函数 | app | Blueprint register |
| sandbox_bp.py | def api_intel_status | 函数 |  | 情报源存活状态 + 脑库条数 |
| sandbox_bp.py | def api_intel_recent | 函数 |  | 最新情报脑库内容 (支持 limit/source 参数, 默认 20 条) |
| sandbox_bp.py | def api_warden_status | 函数 |  | 仙女座托管者全系统健康快照 (只读) |
| sandbox_bp.py | def api_screen_status | 函数 |  | 屏幕监控守护状态 (进程存活 + 最近事件统计) |
| sandbox_bp.py | def api_screen_recent | 函数 |  | 最近屏幕事件 (支持 limit / severity / type 参数) |
| sandbox_bp.py | def api_data_anomalies | 函数 |  | 数据异常列表 (支持 limit / severity / type / res |
| sandbox_bp.py | def api_data_health | 函数 |  | 数据健康总览 — 各 DB 表行数 + 最新时间 + 过期状态 |
| sandbox_bp.py | def _run_full_finance_audit | 函数 |  | 执行一次完整金融审计 (返回 report dict, 同时写入 mt_fina |
| sandbox_bp.py | def _ensure_finance_ledger | 函数 |  | 确保 mt_bank_withdrawal + mt_finance_meeti |
| sandbox_bp.py | def api_bank_withdraw | 函数 |  | 🏦 存银行卡（真提现）— 必须经过金融团队开会表决

红线：提现后账户总量 ≥  |
| sandbox_bp.py | def api_bank_withdrawals | 函数 |  | 🏦 银行存款流水历史 |
| sandbox_bp.py | def api_finance_meetings | 函数 |  | 🏛️ 金融团队会议记录 |
| sandbox_bp.py | def api_audit_run | 函数 |  | 🏛️ 即时触发全量金融合规审计 (CFO+精算师+CPA+审计师) |
| sandbox_bp.py | def api_audit_logs | 函数 |  | 审计日志历史 (默认最新 20 条) |
| sandbox_bp.py | def api_audit_task_hall | 函数 |  | 审计异常触发的任务大厅 |
| sandbox_bp.py | def api_audit_close_task | 函数 |  | 关闭审计任务 (复盘完成) |
| sandbox_bp.py | def api_audit_ledger | 函数 |  | 每笔进出账核对明细 (CPA 核账视角) |
| gobelin_bp.py | def _probe_daemon | 函数 | name | 探测 daemon 是否在跑 (ps + 文件名模糊匹配) |
| gobelin_bp.py | def _probe_blueprints | 函数 |  | 探测 Flask 已注册的蓝图 |
| gobelin_bp.py | def _probe_engine_files | 函数 |  | engines 目录下 .py 文件数量 |
| gobelin_bp.py | def _probe_blueprint_files | 函数 |  | blueprints 目录下 .py 文件数量 |
| gobelin_bp.py | def _probe_db | 函数 |  | DB 健康 (通用 sqlite3) |
| gobelin_bp.py | def gobelin_status | 函数 |  | 古灵阁总状态 — 聚合所有子系统 |
| gobelin_bp.py | def gobelin_daemons | 函数 |  | 快速 daemons 列表 |
| gobelin_bp.py | def api_gobelin_system | 函数 |  |  |
| gobelin_bp.py | def api_gobelin_subsystem | 函数 | key |  |
| gobelin_bp.py | def api_gobelin_status_v2 | 函数 |  |  |
| gobelin_bp.py | def register_gobelin_bp | 函数 | app | 注册到 Flask app |
| gobelin_shield_bp.py | def _db | 函数 |  |  |
| gobelin_shield_bp.py | def _init_tables | 函数 |  |  |
| gobelin_shield_bp.py | def shield_status | 函数 |  |  |
| gobelin_shield_bp.py | def audit_dimensions | 函数 |  | 返回所有 29 安全维度定义 |
| gobelin_shield_bp.py | def audit_full_scan | 函数 |  | 全量安全扫描 — 扫所有 29 维度

Body: {"focus": "all |
| gobelin_shield_bp.py | def audit_single_dim | 函数 | dim_code | 单维度手动检查 |
| gobelin_shield_bp.py | def _run_dimension_check | 函数 | code, dim | 执行单个安全维度检查 — 返回 {status, risk_score, fin |
| gobelin_shield_bp.py | def _table_exists | 函数 | c, table_name |  |
| gobelin_shield_bp.py | def bus_publish | 函数 |  |  |
| gobelin_shield_bp.py | def bus_events | 函数 |  |  |
| gobelin_shield_bp.py | def bus_forces | 函数 |  |  |
| gobelin_shield_bp.py | def customs_check | 函数 |  |  |
| gobelin_shield_bp.py | def customs_audit | 函数 |  |  |
| gobelin_shield_bp.py | def andromeda_ingest | 函数 |  |  |
| gobelin_shield_bp.py | def andromeda_feed | 函数 |  |  |
| gobelin_shield_bp.py | def iceberg_inject | 函数 |  |  |
| gobelin_shield_bp.py | def iceberg_proposal | 函数 |  |  |
| gobelin_shield_bp.py | def comfy_submit | 函数 |  |  |
| gobelin_shield_bp.py | def comfy_jobs | 函数 |  |  |
| gobelin_shield_bp.py | def sa_status | 函数 |  | SA 双密钥在位状态查询 |
| gobelin_shield_bp.py | def sa_verify | 函数 |  | 强制触发 SA 双密钥验证 |
| gobelin_shield_bp.py | def sa_audit | 函数 |  | SA 操作审计日志 |
| gobelin_shield_bp.py | def peacekeeping_status | 函数 |  | 维和部队 (白帽子/灾备/法律/应急) 协同总览 |
| gobelin_shield_bp.py | def customs_status | 函数 |  | 海关总署协同总览 |
| gobelin_shield_bp.py | def centers_status | 函数 |  | 所有中心协同总览 |
| gobelin_shield_bp.py | def _dispatch_event | 函数 | event_type, source, target, pa |  |
| gobelin_shield_bp.py | def _dispatch_to_iceberg | 函数 | event_id, event_type, source_f |  |
| gobelin_shield_bp.py | def _feed_brain | 函数 | source, content, flow_id |  |
| gobelin_writing_bp.py | def _db | 函数 |  |  |
| gobelin_writing_bp.py | def _init_tables | 函数 |  |  |
| gobelin_writing_bp.py | def api_writing_params | 函数 |  | 返回所有创作参数枚举 — 前端创作台用 |
| gobelin_writing_bp.py | def api_writing_create | 函数 |  | 核心创作入口 — 一句话中心思想 → 完整作品

body = {
    "c |
| gobelin_writing_bp.py | def _auto_reference_works | 函数 | genre, media_fmt | 仙女自动匹配参考作品 (简版 — 真实应查向量库) |
| gobelin_writing_bp.py | def _auto_rhythm | 函数 | media_fmt, target_words | 自动节奏曲线建议 |
| gobelin_writing_bp.py | def _generate_outline | 函数 | core_idea, genre, media_fmt, s | 自动大纲 (简版 — 真实应调 AI) |
| gobelin_writing_bp.py | def _auto_title | 函数 | core_idea, genre | 自动标题 |
| gobelin_writing_bp.py | def _call_ai_generate | 函数 | core_idea, params | 调用 AI 生文 — 优先本地 ollama, 失败返回模拟内容
真实接入: o |
| gobelin_writing_bp.py | def _feed_writing_to_brain | 函数 | conn, project_id, title, core_ | 投喂 AI 脑库 |
| gobelin_writing_bp.py | def api_writing_revise | 函数 | pid | 迭代改写: 扩写 / 缩写 / 改风格 / 续写 |
| gobelin_writing_bp.py | def _call_ai_revise | 函数 | old_content, action, instructi | AI 改写 (简版, 降级返回占位) |
| gobelin_writing_bp.py | def api_writing_projects | 函数 |  | 我的创作项目列表 |
| gobelin_writing_bp.py | def api_writing_project_deta | 函数 | pid | 项目详情 + 所有迭代版本 |
| gobelin_writing_bp.py | def api_writing_export | 函数 | pid, fmt | 导出格式: txt / md / script / shortvideo / j |
| gobelin_writing_bp.py | def _format_as_script | 函数 | content, title | 把正文转剧本格式 |
| gobelin_writing_bp.py | def register_gobelin_writing | 函数 | app | 注册到 Flask app |
| sandbox_bp.py | def _cached_realtime | 函数 |  | 带缓存的 _load_realtime() — 30s 内重复调用直接返回 |
| sandbox_bp.py | def _get_db | 函数 |  |  |
| sandbox_bp.py | def api_account | 函数 |  | 账户状态 — 快速聚合(不调 broker 适配器,避免 5s 超时) |
| sandbox_bp.py | def api_positions | 函数 |  | 当前持仓 — 带实时行情 |
| sandbox_bp.py | def api_trades | 函数 |  | 今日交易流水 (mt_trade_log) — 带 realized_pnl 自 |
| sandbox_bp.py | def api_decisions | 函数 |  | 决策流水 — 从 JSONL 文件读最新 N 条 |
| sandbox_bp.py | def api_trades_jsonl | 函数 |  | 交易复盘日志 (含自动生成的经验教训) |
| sandbox_bp.py | def api_radar | 函数 |  | 实时行情 + 异动汇总 |
| sandbox_bp.py | def api_events | 函数 |  | 实时事件 — 从协作总线读今日事件, 去重清洗后返回 |
| sandbox_bp.py | def _sina_daily_kline | 函数 | secid, days | 新浪日线 K 线 — 给 MDS 没有的自选股补数据
secid: sh6000 |
| sandbox_bp.py | def api_kline | 函数 |  | K线数据 — 大盘 + 自选池
?symbol=000001 只返回上证
?da |
| sandbox_bp.py | def api_status | 函数 |  | 系统状态 — daemon + Flask + DB + heartbeat ( |
| sandbox_bp.py | def api_review | 函数 |  | 今日复盘 — 从协作总线 + SQLite 复盘会话表取 (含 5 层会议详情) |
| sandbox_bp.py | def api_trigger_review | 函数 |  | 手动触发复盘 — review_type: 'noon' / 'close' / |
| sandbox_bp.py | def api_ai_agents | 函数 |  | 🧜 仙女座 AI 指挥中枢 — 返回所有 AI 员工实时状态 |
| sandbox_bp.py | def api_ai_dispatch | 函数 |  | 🧜 仙女座指令派发 — 给 AI 员工派任务 |
| sandbox_bp.py | def _run_eng_review | 函数 | review_type | 隔离 wrapper — 避免 Flask 主路由内调用阻塞 |
| sandbox_bp.py | def _ensure_gobelin | 函数 |  | 确保古灵阁表存在 + summary 首行 |
| sandbox_bp.py | def _gobelin_read | 函数 |  | 读古灵阁当前余额 |
| sandbox_bp.py | def _gobelin_lock | 函数 | amount, reason, board_vote | 执行锁利 — 写入 savings 记录 + 更新 summary |
| sandbox_bp.py | def api_gobelin | 函数 |  | 🏛️ 古灵阁账户详情 — 累计锁利 / 历史记录 |
| sandbox_bp.py | def api_board_lock_profits | 函数 |  | 🏛️ 董事会锁利研判 + 执行 — AI 军团自动开会投票 |
| sandbox_bp.py | def api_board_decide_sell | 函数 |  | 收市 AI 军团研判卖哪些持仓 |
| sandbox_bp.py | def api_execute_sell | 函数 |  | Execute real sell - changes cash + posit |
| sandbox_bp.py | def api_deposit_gobelin | 函数 |  | Deposit to Gobelin bank card - verify re |
| sandbox_bp.py | def register_sandbox_bp | 函数 | app | Blueprint register |
| sandbox_bp.py | def api_intel_status | 函数 |  | 情报源存活状态 + 脑库条数 |
| sandbox_bp.py | def api_intel_recent | 函数 |  | 最新情报脑库内容 (支持 limit/source 参数, 默认 20 条) |
| sandbox_bp.py | def api_warden_status | 函数 |  | 仙女座托管者全系统健康快照 (只读) |
| sandbox_bp.py | def api_screen_status | 函数 |  | 屏幕监控守护状态 (进程存活 + 最近事件统计) |
| sandbox_bp.py | def api_screen_recent | 函数 |  | 最近屏幕事件 (支持 limit / severity / type 参数) |
| sandbox_bp.py | def api_data_anomalies | 函数 |  | 数据异常列表 (支持 limit / severity / type / res |
| sandbox_bp.py | def api_data_health | 函数 |  | 数据健康总览 — 各 DB 表行数 + 最新时间 + 过期状态 |
| sandbox_bp.py | def _run_full_finance_audit | 函数 |  | 执行一次完整金融审计 (返回 report dict, 同时写入 mt_fina |
| sandbox_bp.py | def _ensure_finance_ledger | 函数 |  | 确保 mt_bank_withdrawal + mt_finance_meeti |
| sandbox_bp.py | def api_bank_withdraw | 函数 |  | 🏦 存银行卡（真提现）— 必须经过金融团队开会表决

红线：提现后账户总量 ≥  |
| sandbox_bp.py | def api_bank_withdrawals | 函数 |  | 🏦 银行存款流水历史 |
| sandbox_bp.py | def api_finance_meetings | 函数 |  | 🏛️ 金融团队会议记录 |
| sandbox_bp.py | def api_audit_run | 函数 |  | 🏛️ 即时触发全量金融合规审计 (CFO+精算师+CPA+审计师) |
| sandbox_bp.py | def api_audit_logs | 函数 |  | 审计日志历史 (默认最新 20 条) |
| sandbox_bp.py | def api_audit_task_hall | 函数 |  | 审计异常触发的任务大厅 |
| sandbox_bp.py | def api_audit_close_task | 函数 |  | 关闭审计任务 (复盘完成) |
| sandbox_bp.py | def api_audit_ledger | 函数 |  | 每笔进出账核对明细 (CPA 核账视角) |
| team_collab_bp.py | def _db | 函数 |  |  |
| team_collab_bp.py | def _row | 函数 | r |  |
| team_collab_bp.py | def collab_overview | 函数 |  |  |
| team_collab_bp.py | def collab_channels | 函数 |  |  |
| team_collab_bp.py | def collab_channel | 函数 | cid |  |
| team_collab_bp.py | def collab_feed | 函数 |  |  |
| team_collab_bp.py | def collab_say | 函数 | cid |  |
| team_collab_bp.py | def collab_pulse | 函数 |  |  |
| team_collab_bp.py | def collab_rebuild | 函数 |  |  |
| gobelin_shield_bp.py | def _db | 函数 |  |  |
| gobelin_shield_bp.py | def _init_tables | 函数 |  |  |
| gobelin_shield_bp.py | def shield_status | 函数 |  |  |
| gobelin_shield_bp.py | def audit_dimensions | 函数 |  | 返回所有 29 安全维度定义 |
| gobelin_shield_bp.py | def audit_full_scan | 函数 |  | 全量安全扫描 — 扫所有 29 维度

Body: {"focus": "all |
| gobelin_shield_bp.py | def audit_single_dim | 函数 | dim_code | 单维度手动检查 |
| gobelin_shield_bp.py | def _run_dimension_check | 函数 | code, dim | 执行单个安全维度检查 — 返回 {status, risk_score, fin |
| gobelin_shield_bp.py | def _table_exists | 函数 | c, table_name |  |
| gobelin_shield_bp.py | def bus_publish | 函数 |  |  |
| gobelin_shield_bp.py | def bus_events | 函数 |  |  |
| gobelin_shield_bp.py | def bus_forces | 函数 |  |  |
| gobelin_shield_bp.py | def customs_check | 函数 |  |  |
| gobelin_shield_bp.py | def customs_audit | 函数 |  |  |
| gobelin_shield_bp.py | def andromeda_ingest | 函数 |  |  |
| gobelin_shield_bp.py | def andromeda_feed | 函数 |  |  |
| gobelin_shield_bp.py | def iceberg_inject | 函数 |  |  |
| gobelin_shield_bp.py | def iceberg_proposal | 函数 |  |  |
| gobelin_shield_bp.py | def comfy_submit | 函数 |  |  |
| gobelin_shield_bp.py | def comfy_jobs | 函数 |  |  |
| gobelin_shield_bp.py | def sa_status | 函数 |  | SA 双密钥在位状态查询 |
| gobelin_shield_bp.py | def sa_verify | 函数 |  | 强制触发 SA 双密钥验证 |
| gobelin_shield_bp.py | def sa_audit | 函数 |  | SA 操作审计日志 |
| gobelin_shield_bp.py | def peacekeeping_status | 函数 |  | 维和部队 (白帽子/灾备/法律/应急) 协同总览 |
| gobelin_shield_bp.py | def customs_status | 函数 |  | 海关总署协同总览 |
| gobelin_shield_bp.py | def centers_status | 函数 |  | 所有中心协同总览 |
| gobelin_shield_bp.py | def _dispatch_event | 函数 | event_type, source, target, pa |  |
| gobelin_shield_bp.py | def _dispatch_to_iceberg | 函数 | event_id, event_type, source_f |  |
| gobelin_shield_bp.py | def _feed_brain | 函数 | source, content, flow_id |  |
| gobelin_shield_bp.py | def _db | 函数 |  |  |
| gobelin_shield_bp.py | def _init_tables | 函数 |  |  |
| gobelin_shield_bp.py | def shield_status | 函数 |  |  |
| gobelin_shield_bp.py | def audit_dimensions | 函数 |  | 返回所有 29 安全维度定义 |
| gobelin_shield_bp.py | def audit_full_scan | 函数 |  | 全量安全扫描 — 扫所有 29 维度

Body: {"focus": "all |
| gobelin_shield_bp.py | def audit_single_dim | 函数 | dim_code | 单维度手动检查 |
| gobelin_shield_bp.py | def _run_dimension_check | 函数 | code, dim | 执行单个安全维度检查 — 返回 {status, risk_score, fin |
| gobelin_shield_bp.py | def _table_exists | 函数 | c, table_name |  |
| gobelin_shield_bp.py | def bus_publish | 函数 |  |  |
| gobelin_shield_bp.py | def bus_events | 函数 |  |  |
| gobelin_shield_bp.py | def bus_forces | 函数 |  |  |
| gobelin_shield_bp.py | def customs_check | 函数 |  |  |
| gobelin_shield_bp.py | def customs_audit | 函数 |  |  |
| gobelin_shield_bp.py | def andromeda_ingest | 函数 |  |  |
| gobelin_shield_bp.py | def andromeda_feed | 函数 |  |  |
| gobelin_shield_bp.py | def iceberg_inject | 函数 |  |  |
| gobelin_shield_bp.py | def iceberg_proposal | 函数 |  |  |
| gobelin_shield_bp.py | def comfy_submit | 函数 |  |  |
| gobelin_shield_bp.py | def comfy_jobs | 函数 |  |  |
| gobelin_shield_bp.py | def sa_status | 函数 |  | SA 双密钥在位状态查询 |
| gobelin_shield_bp.py | def sa_verify | 函数 |  | 强制触发 SA 双密钥验证 |
| gobelin_shield_bp.py | def sa_audit | 函数 |  | SA 操作审计日志 |
| gobelin_shield_bp.py | def peacekeeping_status | 函数 |  | 维和部队 (白帽子/灾备/法律/应急) 协同总览 |
| gobelin_shield_bp.py | def customs_status | 函数 |  | 海关总署协同总览 |
| gobelin_shield_bp.py | def centers_status | 函数 |  | 所有中心协同总览 |
| gobelin_shield_bp.py | def _dispatch_event | 函数 | event_type, source, target, pa |  |
| gobelin_shield_bp.py | def _dispatch_to_iceberg | 函数 | event_id, event_type, source_f |  |
| gobelin_shield_bp.py | def _feed_brain | 函数 | source, content, flow_id |  |
| team_collab_bp.py | def _db | 函数 |  |  |
| team_collab_bp.py | def _row | 函数 | r |  |
| team_collab_bp.py | def collab_overview | 函数 |  |  |
| team_collab_bp.py | def collab_channels | 函数 |  |  |
| team_collab_bp.py | def collab_channel | 函数 | cid |  |
| team_collab_bp.py | def collab_feed | 函数 |  |  |
| team_collab_bp.py | def collab_say | 函数 | cid |  |
| team_collab_bp.py | def collab_pulse | 函数 |  |  |
| team_collab_bp.py | def collab_rebuild | 函数 |  |  |
| gobelin_bp.py | def _now | 函数 |  |  |
| gobelin_bp.py | def _add_scope_meta | 函数 | response_dict, scope | 给每个响应自动加 scope 元信息, 前端可校验 |
| gobelin_bp.py | def _engines | 函数 |  |  |
| gobelin_bp.py | def _row_to_dict | 函数 | row |  |
| gobelin_bp.py | def _conn | 函数 |  |  |
| gobelin_bp.py | def health | 函数 |  |  |
| gobelin_bp.py | def seal_status | 函数 |  |  |
| gobelin_bp.py | def seal_audit | 函数 |  |  |
| gobelin_bp.py | def seal_by_proposal | 函数 | proposal_id |  |
| gobelin_bp.py | def seal_request | 函数 |  |  |
| gobelin_bp.py | def seal_verify | 函数 |  |  |
| gobelin_bp.py | def seal_consume | 函数 |  |  |
| gobelin_bp.py | def seal_auto_grant | 函数 |  |  |
| gobelin_bp.py | def parliament_proposal | 函数 | proposal_id |  |
| gobelin_bp.py | def parliament_session | 函数 | session_id |  |
| gobelin_bp.py | def parliament_vote | 函数 | proposal_id |  |
| gobelin_bp.py | def parliament_vote_all | 函数 |  |  |
| gobelin_bp.py | def proposal_create | 函数 |  |  |
| gobelin_bp.py | def proposals_list | 函数 |  |  |
| gobelin_bp.py | def autonomous_report | 函数 |  |  |
| gobelin_bp.py | def autonomous_scan | 函数 |  |  |
| gobelin_bp.py | def autonomous_cycle | 函数 |  | 完整自动投资 cycle (行情→提案→议会→发章→执行) |
| gobelin_bp.py | def autonomous_execute | 函数 |  | 只执行已发章的交易 |
| gobelin_bp.py | def _gobelin_conn | 函数 |  |  |
| gobelin_bp.py | def account_refresh | 函数 |  | 刷新所有持仓价格 + 汇总账户 PnL (用真实行情) |
| gobelin_bp.py | def account_overview | 函数 |  | Gobelin Bank 总账 (真实资产, 不混沙盘!) |
| gobelin_bp.py | def positions_list | 函数 |  | 持仓列表 (带真实 PnL) |
| gobelin_bp.py | def trades_list | 函数 |  | 交易流水 (Gobelin Bank 真实成交) |
| gobelin_bp.py | def dashboard_snapshot | 函数 |  | Gobelin 仪表盘 JSON 快照 — adapter 统一取价 (v2,  |
| gobelin_bp.py | def account_public | 函数 |  |  |
| gobelin_bp.py | def positions_public | 函数 |  |  |
| gobelin_bp.py | def dashboard_snapshot | 函数 |  | 一站式 Gobelin Bank 仪表盘数据 — 使用 gobelin_adap |
| gobelin_bp.py | def compliance_audit | 函数 |  | 合规审计详情 |
| gobelin_bp.py | def scheduler_status | 函数 |  | 调度器运行状态 |
| gobelin_bp.py | def community_health | 函数 |  | AI 社区全景健康体检 |
| gobelin_bp.py | def community_employees | 函数 |  | Gobelin Bank AI 员工列表 (含师徒/岗位/能力) |
| gobelin_bp.py | def community_roles | 函数 |  | Gobelin Bank 岗位图谱 |
| gobelin_bp.py | def community_training | 函数 |  | 培训进度 (最近 50 条) |
| gobelin_bp.py | def community_calibrations | 函数 |  | 反推校正记录 (最近 50 条) |
| gobelin_bp.py | def community_bootstrap | 函数 |  | 触发社区一键初始化 |
| gobelin_bp.py | def _collab_engines | 函数 |  |  |
| gobelin_bp.py | def collab_proposal | 函数 | proposal_id | 查看提案协作方案 + 痕迹 + 纪要 |
| gobelin_bp.py | def collab_analyze | 函数 | proposal_id | 触发提案智能分析 |
| gobelin_bp.py | def collab_dispatch | 函数 | proposal_id | 触发派单 |
| gobelin_bp.py | def collab_run_pending | 函数 |  | 批量处理 PENDING 提案 |
| gobelin_bp.py | def collab_traces | 函数 |  | 最近 50 条协作痕迹 |
| gobelin_bp.py | def collab_growth | 函数 |  | AI 成长追踪 |
| gobelin_bp.py | def collab_minutes | 函数 | plan_id | 协作纪要 Markdown |
| gobelin_bp.py | def register_gobelin_bp | 函数 | app | 在 Flask app 上注册 Gobelin Bank Blueprint。
 |
| gobelin_bp.py | def gobelin_view | 函数 |  | HTML 仪表盘 (浏览器直接看) |
| gobelin_music_bp.py | def _db | 函数 |  |  |
| gobelin_music_bp.py | def _ensure_tables | 函数 |  |  |
| gobelin_music_bp.py | def _ollama_available | 函数 |  |  |
| gobelin_music_bp.py | def _call_ollama | 函数 | prompt, model, num_predict, te |  |
| gobelin_music_bp.py | def _gen_full_track | 函数 | title, idea, genre, mood, stru |  |
| gobelin_music_bp.py | def health | 函数 |  |  |
| gobelin_music_bp.py | def list_genres | 函数 |  |  |
| gobelin_music_bp.py | def generate | 函数 |  | 完整歌曲生成 |
| gobelin_music_bp.py | def list_projects | 函数 |  |  |
| gobelin_music_bp.py | def get_project | 函数 | pid |  |
| gobelin_music_bp.py | def register_gobelin_music_b | 函数 | app |  |
| gobelin_shield_bp.py | def _shield_role_gate | 函数 |  |  |
| gobelin_shield_bp.py | def _db | 函数 |  |  |
| gobelin_shield_bp.py | def _init_tables | 函数 |  |  |
| gobelin_shield_bp.py | def shield_status | 函数 |  |  |
| gobelin_shield_bp.py | def audit_dimensions | 函数 |  | 返回所有 29 安全维度定义 |
| gobelin_shield_bp.py | def audit_full_scan | 函数 |  | 全量安全扫描 — 扫所有 29 维度

Body: {"focus": "all |
| gobelin_shield_bp.py | def audit_single_dim | 函数 | dim_code | 单维度手动检查 |
| gobelin_shield_bp.py | def _run_dimension_check | 函数 | code, dim | 执行单个安全维度检查 — 返回 {status, risk_score, fin |
| gobelin_shield_bp.py | def _table_exists | 函数 | c, table_name |  |
| gobelin_shield_bp.py | def bus_publish | 函数 |  |  |
| gobelin_shield_bp.py | def bus_events | 函数 |  |  |
| gobelin_shield_bp.py | def bus_forces | 函数 |  |  |
| gobelin_shield_bp.py | def customs_check | 函数 |  |  |
| gobelin_shield_bp.py | def customs_audit | 函数 |  |  |
| gobelin_shield_bp.py | def andromeda_ingest | 函数 |  |  |
| gobelin_shield_bp.py | def andromeda_feed | 函数 |  |  |
| gobelin_shield_bp.py | def iceberg_inject | 函数 |  |  |
| gobelin_shield_bp.py | def iceberg_proposal | 函数 |  |  |
| gobelin_shield_bp.py | def comfy_submit | 函数 |  |  |
| gobelin_shield_bp.py | def comfy_jobs | 函数 |  |  |
| gobelin_shield_bp.py | def sa_status | 函数 |  | SA 双密钥在位状态查询 |
| gobelin_shield_bp.py | def sa_verify | 函数 |  | 强制触发 SA 双密钥验证 |
| gobelin_shield_bp.py | def sa_audit | 函数 |  | SA 操作审计日志 |
| gobelin_shield_bp.py | def peacekeeping_status | 函数 |  | 维和部队 (白帽子/灾备/法律/应急) 协同总览 |
| gobelin_shield_bp.py | def customs_status | 函数 |  | 海关总署协同总览 |
| gobelin_shield_bp.py | def centers_status | 函数 |  | 所有中心协同总览 — 22 中心全量 |
| gobelin_shield_bp.py | def retro_complete | 函数 |  | POST /api/shield/retro/complete — 历史提案复盘 |
| gobelin_shield_bp.py | def _dispatch_event | 函数 | event_type, source, target, pa |  |
| gobelin_shield_bp.py | def _dispatch_to_iceberg | 函数 | event_id, event_type, source_f |  |
| gobelin_shield_bp.py | def _feed_brain | 函数 | source, content, flow_id |  |
| gobelin_video_bp.py | def _db | 函数 |  |  |
| gobelin_video_bp.py | def _ensure_tables | 函数 |  |  |
| gobelin_video_bp.py | def _ollama_available | 函数 |  |  |
| gobelin_video_bp.py | def _call_ollama | 函数 | prompt, model, num_predict, te |  |
| gobelin_video_bp.py | def _gen_shots | 函数 | title, idea, fmt_label, style, |  |
| gobelin_video_bp.py | def _gen_voiceover | 函数 | title, idea, emotion, shots, m |  |
| gobelin_video_bp.py | def health | 函数 |  |  |
| gobelin_video_bp.py | def list_formats | 函数 |  |  |
| gobelin_video_bp.py | def generate | 函数 |  | 完整视频脚本生成: 创意 → 分镜 → 配音 |
| gobelin_video_bp.py | def list_projects | 函数 |  |  |
| gobelin_video_bp.py | def get_project | 函数 | pid |  |
| gobelin_video_bp.py | def export_shots | 函数 | pid | 导出分镜为 JSON, 供 AI 视频生成管线使用 |
| gobelin_video_bp.py | def register_gobelin_video_b | 函数 | app |  |
| gobelin_writing_bp.py | def _db | 函数 |  |  |
| gobelin_writing_bp.py | def _init_tables | 函数 |  |  |
| gobelin_writing_bp.py | def api_writing_params | 函数 |  | 返回所有创作参数枚举 — 前端创作台用 |
| gobelin_writing_bp.py | def api_writing_create | 函数 |  | v26.12 整合版 — 代理到 copy_studio engine.quic |
| gobelin_writing_bp.py | def api_writing_genres | 函数 |  | 兼容 writing_server.py /api/writing/genres |
| gobelin_writing_bp.py | def api_writing_models | 函数 |  | 兼容 writing_server.py /api/writing/models |
| gobelin_writing_bp.py | def api_writing_generate | 函数 |  | v26.12 整合版 — 兼容 writing_server.py 风格, 代理 |
| gobelin_writing_bp.py | def _auto_reference_works | 函数 | genre, media_fmt | 仙女自动匹配参考作品 (简版 — 真实应查向量库) |
| gobelin_writing_bp.py | def _auto_rhythm | 函数 | media_fmt, target_words | 自动节奏曲线建议 |
| gobelin_writing_bp.py | def _generate_outline | 函数 | core_idea, genre, media_fmt, s | 自动大纲 (简版 — 真实应调 AI) |
| gobelin_writing_bp.py | def _auto_title | 函数 | core_idea, genre | 自动标题 |
| gobelin_writing_bp.py | def _call_ai_generate | 函数 | core_idea, params | 调用 AI 生文 — 优先本地 ollama, 失败返回模拟内容
真实接入: o |
| gobelin_writing_bp.py | def _feed_writing_to_brain | 函数 | conn, project_id, title, core_ | 投喂 AI 脑库 |
| gobelin_writing_bp.py | def api_writing_revise | 函数 | pid | 迭代改写: 扩写 / 缩写 / 改风格 / 续写 — 代理到 copy_stud |
| gobelin_writing_bp.py | def api_writing_projects | 函数 |  | 我的创作项目列表 — copy_studio mt_copy_projects  |
| gobelin_writing_bp.py | def api_writing_project_deta | 函数 | pid | 项目详情 — copy_studio 优先, fallback legacy |
| gobelin_writing_bp.py | def api_writing_export | 函数 | pid, fmt | 导出格式: txt / md / json — copy_studio 优先,  |
| gobelin_writing_bp.py | def register_gobelin_writing | 函数 | app | 注册到 Flask app |
| lab_sandbox_bp.py | **class _StubBP** | 类 | |  |
| | ↳ def __init__ | 方法 | self, name, **kw |  |
| | ↳ def route | 方法 | self, rule, **kw |  |
| lab_sandbox_bp.py | **class _StubReq** | 类 | |  |
| | ↳ def json | 方法 | self |  |
| | ↳ def get_json | 方法 | self, silent |  |
| | ↳ def args | 方法 | self |  |
| lab_sandbox_bp.py | **class _StubJ** | 类 | |  |
| | ↳ def dumps | 方法 | x, **kw |  |
| lab_sandbox_bp.py | def _get_engine | 函数 |  |  |
| lab_sandbox_bp.py | def _ok | 函数 | data, **extra |  |
| lab_sandbox_bp.py | def _err | 函数 | msg, code |  |
| lab_sandbox_bp.py | def list_experiments | 函数 |  | 所有实验 (可按 status 过滤) |
| lab_sandbox_bp.py | def create_experiment | 函数 |  | 创建实验 (自动加 36 AI 员工) |
| lab_sandbox_bp.py | def get_experiment | 函数 | exp_id | 实验详情 (组合/交易/排名) |
| lab_sandbox_bp.py | def set_experiment_status | 函数 | exp_id | 结束/暂停/重启实验 |
| lab_sandbox_bp.py | def join_experiment | 函数 | exp_id | 人类加入实验 |
| lab_sandbox_bp.py | def list_participants | 函数 | exp_id |  |
| lab_sandbox_bp.py | def get_rankings | 函数 | exp_id | 团队排名 (基于总资产估算) |
| lab_sandbox_bp.py | def place_trade | 函数 | exp_id | 模拟下单 + AI 点评 (同步返回) |
| lab_sandbox_bp.py | def list_trades | 函数 | exp_id | 实验所有交易 |
| lab_sandbox_bp.py | def get_portfolio | 函数 | exp_id | 实验所有持仓 |
| lab_sandbox_bp.py | def run_review | 函数 | exp_id | AI 复盘 (同步, 可能耗时 30-60s — 已在 CLI 验证 Ollam |
| lab_sandbox_bp.py | def feed_brain | 函数 | exp_id | 教训投喂脑库 |
| lab_sandbox_bp.py | def get_report | 函数 | exp_id | 查看复盘报告 |
| lab_sandbox_bp.py | def send_chat | 函数 | exp_id | AI 老师对话 |
| lab_sandbox_bp.py | def get_chat | 函数 | exp_id | 对话历史 |
| lab_sandbox_bp.py | def quote | 函数 | symbol | 实时行情 (腾讯 API) |
| lab_sandbox_bp.py | def batch_quotes | 函数 |  | 批量行情 |
| lab_sandbox_bp.py | def list_tools | 函数 | exp_id | 金融工具清单 (沙盘内可用引擎列表) — 只暴露名称, 不影响真实数据 |
| lab_sandbox_bp.py | def run_tool | 函数 | exp_id | 运行金融工具 (只读, 不写真实表) |
| lab_sandbox_bp.py | def health | 函数 |  |  |
| lab_sandbox_bp.py | def register_lab_sandbox_blu | 函数 | app | 把 lab_bp 注册到 Flask app, 并确保 6 张表存在 |
| sandbox_bp.py | def _trade_gate | 函数 | f | 装饰器: 交易写操作强制角色 + 交易日护栏 (周末/法定假日自动拒绝) |
| sandbox_bp.py | def _cached_realtime | 函数 |  | 带缓存的 _load_realtime() — 30s 内重复调用直接返回 |
| sandbox_bp.py | def _get_db | 函数 |  |  |
| sandbox_bp.py | def api_account | 函数 |  | 账户状态 — 快速聚合(不调 broker 适配器,避免 5s 超时) |
| sandbox_bp.py | def api_positions | 函数 |  | 当前持仓 — 带实时行情 (死代码, stock_sandbox_bp 覆盖) |
| sandbox_bp.py | def api_trades | 函数 |  | 今日交易流水 (mt_trade_log) — 带 realized_pnl 自 |
| sandbox_bp.py | def api_decisions | 函数 |  | 决策流水 — 从 JSONL 文件读最新 N 条 |
| sandbox_bp.py | def api_trades_jsonl | 函数 |  | 交易复盘日志 (含自动生成的经验教训) |
| sandbox_bp.py | def api_radar | 函数 |  | 实时行情 + 异动汇总 |
| sandbox_bp.py | def api_events | 函数 |  | 实时事件 — 从协作总线读今日事件, 去重清洗后返回 |
| sandbox_bp.py | def _sina_daily_kline | 函数 | secid, days | 新浪日线 K 线 — 给 MDS 没有的自选股补数据
secid: sh6000 |
| sandbox_bp.py | def api_kline | 函数 |  | K线数据 — 大盘 + 自选池
?symbol=000001 只返回上证
?da |
| sandbox_bp.py | def api_status | 函数 |  | 系统状态 — daemon + Flask + DB + heartbeat ( |
| sandbox_bp.py | def api_review | 函数 |  | 今日复盘 — 从协作总线 + SQLite 复盘会话表取 (含 5 层会议详情) |
| sandbox_bp.py | def api_trigger_review | 函数 |  | 手动触发复盘 — review_type: 'noon' / 'close' / |
| sandbox_bp.py | def api_ai_agents | 函数 |  | 🧜 仙女座 AI 指挥中枢 — 返回所有 AI 员工实时状态 |
| sandbox_bp.py | def api_ai_dispatch | 函数 |  | 🧜 仙女座指令派发 — 给 AI 员工派任务 |
| sandbox_bp.py | def _run_eng_review | 函数 | review_type | 隔离 wrapper — 避免 Flask 主路由内调用阻塞 |
| sandbox_bp.py | def _ensure_gobelin | 函数 |  | 确保古灵阁表存在 + summary 首行 |
| sandbox_bp.py | def _gobelin_read | 函数 |  | 读古灵阁当前余额 |
| sandbox_bp.py | def _gobelin_lock | 函数 | amount, reason, board_vote | 执行锁利 — 写入 savings 记录 + 更新 summary |
| sandbox_bp.py | def api_gobelin | 函数 |  | 🏛️ 古灵阁账户详情 — 累计锁利 / 历史记录 |
| sandbox_bp.py | def api_board_lock_profits | 函数 |  | 🏛️ 董事会锁利研判 + 执行 — AI 军团自动开会投票 |
| sandbox_bp.py | def api_board_decide_sell | 函数 |  | 收市 AI 军团研判卖哪些持仓 |
| sandbox_bp.py | def api_execute_sell | 函数 |  | Execute real sell - changes cash + posit |
| sandbox_bp.py | def api_deposit_gobelin | 函数 |  | Deposit to Gobelin bank card - verify re |
| sandbox_bp.py | def register_sandbox_bp | 函数 | app | Blueprint register |
| sandbox_bp.py | def api_intel_status | 函数 |  | 情报源存活状态 + 脑库条数 |
| sandbox_bp.py | def api_intel_recent | 函数 |  | 最新情报脑库内容 (支持 limit/source 参数, 默认 20 条) |
| sandbox_bp.py | def api_warden_status | 函数 |  | 仙女座托管者全系统健康快照 (只读) |
| sandbox_bp.py | def api_screen_status | 函数 |  | 屏幕监控守护状态 (进程存活 + 最近事件统计) |
| sandbox_bp.py | def api_screen_recent | 函数 |  | 最近屏幕事件 (支持 limit / severity / type 参数) |
| sandbox_bp.py | def api_data_anomalies | 函数 |  | 数据异常列表 (支持 limit / severity / type / res |
| sandbox_bp.py | def api_data_health | 函数 |  | 数据健康总览 — 各 DB 表行数 + 最新时间 + 过期状态 |
| sandbox_bp.py | def _run_full_finance_audit | 函数 |  | 执行一次完整金融审计 (返回 report dict, 同时写入 mt_fina |
| sandbox_bp.py | def _ensure_finance_ledger | 函数 |  | 确保 mt_bank_withdrawal + mt_finance_meeti |
| sandbox_bp.py | def api_bank_withdraw | 函数 |  | 🏦 存银行卡（真提现）— 必须经过金融团队开会表决

红线：提现后账户总量 ≥  |
| sandbox_bp.py | def api_bank_withdrawals | 函数 |  | 🏦 银行存款流水历史 |
| sandbox_bp.py | def api_finance_meetings | 函数 |  | 🏛️ 金融团队会议记录 |
| sandbox_bp.py | def api_audit_run | 函数 |  | 🏛️ 即时触发全量金融合规审计 (CFO+精算师+CPA+审计师) |
| sandbox_bp.py | def api_audit_logs | 函数 |  | 审计日志历史 (默认最新 20 条) |
| sandbox_bp.py | def api_audit_task_hall | 函数 |  | 审计异常触发的任务大厅 |
| sandbox_bp.py | def api_audit_close_task | 函数 |  | 关闭审计任务 (复盘完成) |
| sandbox_bp.py | def api_audit_ledger | 函数 |  | 每笔进出账核对明细 (CPA 核账视角) |
| stock_sandbox_bp.py | def _db_conn | 函数 |  |  |
| stock_sandbox_bp.py | def _daemon_alive | 函数 | sb | daemon 存活判定: Flask 进程内线程 OR launchd 独立进程 |
| stock_sandbox_bp.py | def api_sessions | 函数 |  | 全部沙盘会话列表 (会话选择器数据源, 含幽灵会话标记) |
| stock_sandbox_bp.py | def api_portfolio_session | 函数 | session_id | 任意会话只读详情 (状态 + 持仓 + 交易) — 独立路由, 不受蓝图共享路由 |
| stock_sandbox_bp.py | def api_status | 函数 |  | 沙盘状态概览 (默认活跃会话; ?session_id= 可只读查看任意历史会话 |
| stock_sandbox_bp.py | def api_tick | 函数 |  | 手动执行一次 tick |
| stock_sandbox_bp.py | def api_simulate | 函数 |  | 模拟一周/一年
body JSON: {
    "days": 10,     |
| stock_sandbox_bp.py | def api_daemon_start | 函数 |  | 启动守护进程 |
| stock_sandbox_bp.py | def api_daemon_stop | 函数 |  | 停止守护进程 |
| stock_sandbox_bp.py | def api_trades | 函数 |  | 交易流水 |
| stock_sandbox_bp.py | def api_positions | 函数 |  | 当前持仓 — portfolio.positions_json 为空时用 mt_ |
| stock_sandbox_bp.py | def api_signals | 函数 |  | 策略信号池 |
| stock_sandbox_bp.py | def api_reports | 函数 |  | 沙盘报告 — session 净值曲线 |
| teacher_sandbox_bp.py | def _get_engine | 函数 |  |  |
| teacher_sandbox_bp.py | def _ok | 函数 | data, **extra |  |
| teacher_sandbox_bp.py | def _err | 函数 | msg, code |  |
| teacher_sandbox_bp.py | def health | 函数 |  |  |
| teacher_sandbox_bp.py | def list_teams | 函数 |  |  |
| teacher_sandbox_bp.py | def create_team | 函数 |  |  |
| teacher_sandbox_bp.py | def get_team | 函数 | team_id |  |
| teacher_sandbox_bp.py | def list_teachers | 函数 | team_id |  |
| teacher_sandbox_bp.py | def submit_lesson | 函数 | team_id |  |
| teacher_sandbox_bp.py | def _tsconn | 函数 |  |  |
| teacher_sandbox_bp.py | def list_lessons | 函数 | team_id |  |
| teacher_sandbox_bp.py | def run_mock | 函数 | team_id, plan_id |  |
| teacher_sandbox_bp.py | def team_reflect | 函数 | team_id |  |
| teacher_sandbox_bp.py | def list_reflections | 函数 | team_id |  |
| teacher_sandbox_bp.py | def get_competency | 函数 | teacher_id |  |
| teacher_sandbox_bp.py | def register_teacher_sandbox | 函数 | app |  |
| team_collab_bp.py | def _db | 函数 |  |  |
| team_collab_bp.py | def _row | 函数 | r |  |
| team_collab_bp.py | def collab_overview | 函数 |  |  |
| team_collab_bp.py | def collab_channels | 函数 |  |  |
| team_collab_bp.py | def collab_channel | 函数 | cid |  |
| team_collab_bp.py | def collab_feed | 函数 |  |  |
| team_collab_bp.py | def collab_say | 函数 | cid |  |
| team_collab_bp.py | def collab_pulse | 函数 |  |  |
| team_collab_bp.py | def collab_rebuild | 函数 |  |  |
| ai_sandbox_tick_engine.p | def _log | 函数 | msg |  |
| ai_sandbox_tick_engine.p | def _db | 函数 |  |  |
| ai_sandbox_tick_engine.p | def _load_positions | 函数 |  | 当前沙盘持仓 → {symbol: {'qty': int, 'avg_cost |
| ai_sandbox_tick_engine.p | def _get_cash | 函数 |  | 沙盘现金余额 |
| ai_sandbox_tick_engine.p | def _sina_quote | 函数 | secids | 新浪实时行情批量拉取 — 纯 urllib, 零依赖 |
| ai_sandbox_tick_engine.p | def _load_realtime | 函数 |  | 拉真实行情 → {symbol: {...}}
双源: MarketDataSe |
| ai_sandbox_tick_engine.p | def _board_debate | 函数 | action, sym, rt, positions, ai | 🆕 董事会派系辩论 — 鹰派(激进) vs 犬派(保守) 左右互搏 + 董事长裁 |
| ai_sandbox_tick_engine.p | def _gen_resolution | 函数 | action, sym, rt, positions, ai | 鹰派犬派辩论 + 董事长裁决 → 人类可读决议文本 |
| ai_sandbox_tick_engine.p | def _eval_buy | 函数 | sym, rt, positions, cash | 买入信号 — 动量策略

AI 模块:
  [momentum_detector |
| ai_sandbox_tick_engine.p | def _eval_sell | 函数 | sym, rt, positions | 卖出信号 — 止损(全清) + 止盈(分批锁利)

止损: 亏损 < -5% → |
| ai_sandbox_tick_engine.p | def _now_cn | 函数 |  | 当前 A 股市场时间 (Asia/Shanghai, 返回 naive date |
| ai_sandbox_tick_engine.p | def _market_phase | 函数 | now | 显式市场状态机 (可传入 now 做边界单测):
  weekend   — 周 |
| ai_sandbox_tick_engine.p | def _is_trading_hours | 函数 | now | 兼容旧 API — 是否处于连续竞价时段 |
| ai_sandbox_tick_engine.p | def _is_pre_open | 函数 | now | 兼容旧 API — 是否处于集合竞价时段 |
| ai_sandbox_tick_engine.p | def _limit_up_down_check | 函数 | price, chg_pct, action, symbol | 涨跌停检查 — 返回阻断原因或 None (可交易)
主板(000/002/60 |
| ai_sandbox_tick_engine.p | def _t1_veto | 函数 | symbol, action | T+1 检查 — 当日买入不能当日卖出 |
| ai_sandbox_tick_engine.p | def run_tick | 函数 |  | 单次 tick (交易时段内下单, 盘前只 publish, 其余时段静默) |
| ai_sandbox_tick_engine.p | def _closed_loop_review | 函数 | order, rt, positions, cash | 🔄 动作闭环审议 — 每个操盘动作先跑一轮闭环再决议

六步闭环:
  ① 模拟 |
| ai_sandbox_tick_engine.p | def _finance_committee_revie | 函数 | stats, trades, positions, rt,  | 🏛️ 金融委员会审议 + Eigenflux 专家会诊

从 DB 拉真实专家  |
| ai_sandbox_tick_engine.p | def _loss_recovery_rescue | 函数 | trades, positions, rt, review_ | 🚨 亏损挽救预案体系 — Loss Recovery Rescue System |
| ai_sandbox_tick_engine.p | def _execute_order | 函数 | order, rt, positions, trades_m | 执行单笔模拟下单 + 自动生成交易经验教训 |
| ai_sandbox_tick_engine.p | def _generate_trade_lesson | 函数 | action, sym, qty, price, rt, o | 🆕 自动生成单笔交易的经验教训 (规则-based, 复盘喂脑库用) |
| ai_sandbox_tick_engine.p | def _persist_review_session | 函数 | session | 复盘会话留档 → JSONL + 协作总线事件 |
| ai_sandbox_tick_engine.p | def _persist_meeting | 函数 | m | 单场会议记录留档 → JSONL (全局唯一 id, 溯源链) |
| ai_sandbox_tick_engine.p | def _gen_meetings | 函数 | review_type, stats, trades, po | 生成 5 层会议颗粒度 — 每场会议独立角色、独立议题、独立结论
meeting |
| ai_sandbox_tick_engine.p | def run_review_session | 函数 | review_type | 复盘会话 — noon (午间) / close (收市)
统一入口, 内部分  |
| ai_sandbox_tick_engine.p | def run_daily_review | 函数 |  | 兼容旧 API — 默认触发收市复盘 (close) |
| ai_sandbox_tick_engine.p | def _review_scheduler | 函数 |  | 复盘定时器 — 每天 11:31 (午间) + 15:05 (收市) 双触发 |
| ai_sandbox_tick_engine.p | def _daily_review_scheduler | 函数 |  | 兼容旧 API — 内部委托给 _review_scheduler |
| ai_sandbox_tick_engine.p | def _offline_learning_schedu | 函数 |  | 休市期间学习循环:
  - 交易时段: 不跑 (避免和实盘 tick 抢资源)
 |
| ai_sandbox_tick_engine.p | def _acquire_single_lock | 函数 |  | 进程级单实例锁 — 防止 launchd 守护进程与 modular_start |
| ai_sandbox_tick_engine.p | def start_sandbox_tick | 函数 | interval | 启动沙盘 tick daemon + 收市复盘定时器 + 休市学习循环 |
| ai_sandbox_tick_engine.p | def _log | 函数 | msg |  |
| ai_sandbox_tick_engine.p | def _db | 函数 |  |  |
| ai_sandbox_tick_engine.p | def _load_positions | 函数 |  | 当前沙盘持仓 → {symbol: {'qty': int, 'avg_cost |
| ai_sandbox_tick_engine.p | def _get_cash | 函数 |  | 沙盘现金余额 |
| ai_sandbox_tick_engine.p | def _sina_quote | 函数 | secids | 新浪实时行情批量拉取 — 纯 urllib, 零依赖 |
| ai_sandbox_tick_engine.p | def _load_realtime | 函数 |  | 拉真实行情 → {symbol: {...}}
双源: MarketDataSe |
| ai_sandbox_tick_engine.p | def _board_debate | 函数 | action, sym, rt, positions, ai | 🆕 董事会派系辩论 — 鹰派(激进) vs 犬派(保守) 左右互搏 + 董事长裁 |
| ai_sandbox_tick_engine.p | def _gen_resolution | 函数 | action, sym, rt, positions, ai | 鹰派犬派辩论 + 董事长裁决 → 人类可读决议文本 |
| ai_sandbox_tick_engine.p | def _eval_buy | 函数 | sym, rt, positions, cash | 买入信号 — 动量策略

AI 模块:
  [momentum_detector |
| ai_sandbox_tick_engine.p | def _eval_sell | 函数 | sym, rt, positions | 卖出信号 — 止损(全清) + 止盈(分批锁利)

止损: 亏损 < -5% → |
| ai_sandbox_tick_engine.p | def _now_cn | 函数 |  | 当前 A 股市场时间 (Asia/Shanghai, 返回 naive date |
| ai_sandbox_tick_engine.p | def _market_phase | 函数 | now | 显式市场状态机 (可传入 now 做边界单测):
  weekend   — 周 |
| ai_sandbox_tick_engine.p | def _is_trading_hours | 函数 | now | 兼容旧 API — 是否处于连续竞价时段 |
| ai_sandbox_tick_engine.p | def _is_pre_open | 函数 | now | 兼容旧 API — 是否处于集合竞价时段 |
| ai_sandbox_tick_engine.p | def _limit_up_down_check | 函数 | price, chg_pct, action, symbol | 涨跌停检查 — 返回阻断原因或 None (可交易)
主板(000/002/60 |
| ai_sandbox_tick_engine.p | def _t1_veto | 函数 | symbol, action | T+1 检查 — 当日买入不能当日卖出 |
| ai_sandbox_tick_engine.p | def run_tick | 函数 |  | 单次 tick (交易时段内下单, 盘前只 publish, 其余时段静默) |
| ai_sandbox_tick_engine.p | def _closed_loop_review | 函数 | order, rt, positions, cash | 🔄 动作闭环审议 — 每个操盘动作先跑一轮闭环再决议

六步闭环:
  ① 模拟 |
| ai_sandbox_tick_engine.p | def _finance_committee_revie | 函数 | stats, trades, positions, rt,  | 🏛️ 金融委员会审议 + Eigenflux 专家会诊

从 DB 拉真实专家  |
| ai_sandbox_tick_engine.p | def _loss_recovery_rescue | 函数 | trades, positions, rt, review_ | 🚨 亏损挽救预案体系 — Loss Recovery Rescue System |
| ai_sandbox_tick_engine.p | def _execute_order | 函数 | order, rt, positions, trades_m | 执行单笔模拟下单 + 自动生成交易经验教训 |
| ai_sandbox_tick_engine.p | def _generate_trade_lesson | 函数 | action, sym, qty, price, rt, o | 🆕 自动生成单笔交易的经验教训 (规则-based, 复盘喂脑库用) |
| ai_sandbox_tick_engine.p | def _persist_review_session | 函数 | session | 复盘会话留档 → JSONL + 协作总线事件 |
| ai_sandbox_tick_engine.p | def _persist_meeting | 函数 | m | 单场会议记录留档 → JSONL (全局唯一 id, 溯源链) |
| ai_sandbox_tick_engine.p | def _gen_meetings | 函数 | review_type, stats, trades, po | 生成 5 层会议颗粒度 — 每场会议独立角色、独立议题、独立结论
meeting |
| ai_sandbox_tick_engine.p | def run_review_session | 函数 | review_type | 复盘会话 — noon (午间) / close (收市)
统一入口, 内部分  |
| ai_sandbox_tick_engine.p | def run_daily_review | 函数 |  | 兼容旧 API — 默认触发收市复盘 (close) |
| ai_sandbox_tick_engine.p | def _run_finance_audit | 函数 |  | 收市金融合规审计 (tick_engine 内置版, 与 sandbox_bp. |
| ai_sandbox_tick_engine.p | def _review_scheduler | 函数 |  | 复盘 + 审计定时器 — 每天 11:31 (午间复盘) + 15:05 (收市 |
| ai_sandbox_tick_engine.p | def _daily_review_scheduler | 函数 |  | 兼容旧 API — 内部委托给 _review_scheduler |
| ai_sandbox_tick_engine.p | def _offline_learning_schedu | 函数 |  | 休市期间学习循环:
  - 交易时段: 不跑 (避免和实盘 tick 抢资源)
 |
| ai_sandbox_tick_engine.p | def _acquire_single_lock | 函数 |  | 进程级单实例锁 — 防止 launchd 守护进程与 modular_start |
| ai_sandbox_tick_engine.p | def start_sandbox_tick | 函数 | interval | 启动沙盘 tick daemon + 收市复盘定时器 + 休市学习循环 |
| ai_sandbox_meeting_auto. | def _db | 函数 |  |  |
| ai_sandbox_meeting_auto. | def _is_trading_day | 函数 | now |  |
| ai_sandbox_meeting_auto. | def _is_last_trading_day_of_ | 函数 | now |  |
| ai_sandbox_meeting_auto. | def _is_friday_trading_day | 函数 | now |  |
| ai_sandbox_meeting_auto. | def _is_year_end_trading_day | 函数 | now |  |
| ai_sandbox_meeting_auto. | def _is_evening_window | 函数 | now | 交易日 15:30 ~ 23:00 在晚间时间窗内 |
| ai_sandbox_meeting_auto. | def _is_evening_half_hour_tr | 函数 | now | 每 30 分钟触发一次 (15:30, 16:00, 16:30, ... 22 |
| ai_sandbox_meeting_auto. | def _is_afternoon_trading_tr | 函数 | now | 交易日 13:00 ~ 15:00 在下午盘时间窗内 |
| ai_sandbox_meeting_auto. | def _afternoon_sequence | 函数 | now | 下午盘循环是第几轮 (1~4) |
| ai_sandbox_meeting_auto. | def get_due_meetings | 函数 | now |  |
| ai_sandbox_meeting_auto. | def _evening_sequence | 函数 | now | 晚间循环是第几轮 (1~15) |
| ai_sandbox_meeting_auto. | def _slot_label | 函数 | slot |  |
| ai_sandbox_meeting_auto. | def _load_eigenflux_experts | 函数 |  | 从 mt_lab_centers 抽 52 个专家 + 内置兜底 |
| ai_sandbox_meeting_auto. | def _pick_roles | 函数 |  |  |
| ai_sandbox_meeting_auto. | def _get_today_stats | 函数 | conn |  |
| ai_sandbox_meeting_auto. | def _get_positions | 函数 | conn |  |
| ai_sandbox_meeting_auto. | def _get_anomalies_today | 函数 | conn |  |
| ai_sandbox_meeting_auto. | def _run_divergent_simulatio | 函数 | evening_seq | 晚间循环 Layer A — 假设性/发散性模拟操盘

每轮抽 3 个随机假设  |
| ai_sandbox_meeting_auto. | def _simulate_expert_reason | 函数 | domain, scenario, direction |  |
| ai_sandbox_meeting_auto. | def _run_grassroots_quick_sy | 函数 | evening_seq | 晚间循环 Layer B — 基层每 30 分钟小组快速复盘

每次 4~6 个 |
| ai_sandbox_meeting_auto. | def _collect_media_materials | 函数 | evening_seq | 晚间循环 Layer C — 媒体素材收集 (mock, 可升级)

收集 FM |
| ai_sandbox_meeting_auto. | def generate_meeting | 函数 | meeting_slot, evening_seq, aft |  |
| ai_sandbox_meeting_auto. | def _generate_afternoon_trad | 函数 | afternoon_seq, now | 下午盘密集循环 — 13:00~15:00 每 30 min 一次, 3 层实时 |
| ai_sandbox_meeting_auto. | def _generate_evening_half_h | 函数 | evening_seq, now | 晚间密集循环 — 每 30 分钟一次, 3 层会议
  Layer A: sim |
| ai_sandbox_meeting_auto. | def _generate_media_intake | 函数 | evening_seq, now | 独立媒体采集 slot (每 60 min, 不绑定晚间循环) |
| ai_sandbox_meeting_auto. | def _save_meetings | 函数 | conn, meetings |  |
| ai_sandbox_meeting_auto. | def _feed_brain | 函数 | conn, meetings, slot |  |
| ai_sandbox_meeting_auto. | def _publish_collab_bus | 函数 | conn, meetings, slot |  |
| ai_sandbox_meeting_auto. | def _audit_shield | 函数 | conn, slot, meeting_count, bra |  |
| ai_sandbox_meeting_auto. | def _dispatch_actions_to_hal | 函数 | conn, meetings, slot |  |
| ai_sandbox_meeting_auto. | def run_meeting_engine | 函数 | now, force_slot |  |
| ai_sandbox_tick_engine.p | def _wrapped_connect | 函数 | *a, **kw |  |
| ai_sandbox_tick_engine.p | def _log | 函数 | msg |  |
| ai_sandbox_tick_engine.p | def _db | 函数 |  |  |
| ai_sandbox_tick_engine.p | def _load_positions | 函数 |  | 当前沙盘持仓 → {symbol: {'qty': int, 'avg_cost |
| ai_sandbox_tick_engine.p | def _get_cash | 函数 |  | 沙盘现金余额 |
| ai_sandbox_tick_engine.p | def _sina_quote | 函数 | secids | 新浪实时行情批量拉取 — 纯 urllib, 零依赖 |
| ai_sandbox_tick_engine.p | def _load_realtime | 函数 |  | 拉真实行情 → {symbol: {...}}
双源: MarketDataSe |
| ai_sandbox_tick_engine.p | def _board_debate | 函数 | action, sym, rt, positions, ai | 🆕 董事会派系辩论 — 鹰派(激进) vs 犬派(保守) 左右互搏 + 董事长裁 |
| ai_sandbox_tick_engine.p | def _gen_resolution | 函数 | action, sym, rt, positions, ai | 鹰派犬派辩论 + 董事长裁决 → 人类可读决议文本 |
| ai_sandbox_tick_engine.p | def _eval_buy | 函数 | sym, rt, positions, cash | 买入信号 — 动量策略

AI 模块:
  [momentum_detector |
| ai_sandbox_tick_engine.p | def _eval_sell | 函数 | sym, rt, positions | 卖出信号 — 止损(全清) + 止盈(分批锁利)

止损: 亏损 < -5% → |
| ai_sandbox_tick_engine.p | def _now_cn | 函数 |  | 当前 A 股市场时间 (Asia/Shanghai, 返回 naive date |
| ai_sandbox_tick_engine.p | def _market_phase | 函数 | now | 显式市场状态机 (可传入 now 做边界单测):
  weekend   — 周 |
| ai_sandbox_tick_engine.p | def _is_trading_hours | 函数 | now | 兼容旧 API — 是否处于连续竞价时段 |
| ai_sandbox_tick_engine.p | def _is_pre_open | 函数 | now | 兼容旧 API — 是否处于集合竞价时段 |
| ai_sandbox_tick_engine.p | def _limit_up_down_check | 函数 | price, chg_pct, action, symbol | 涨跌停检查 — 返回阻断原因或 None (可交易)
主板(000/002/60 |
| ai_sandbox_tick_engine.p | def _t1_veto | 函数 | symbol, action | T+1 检查 — 当日买入不能当日卖出 |
| ai_sandbox_tick_engine.p | def run_tick | 函数 |  | 单次 tick (交易时段内下单, 盘前只 publish, 其余时段静默) |
| ai_sandbox_tick_engine.p | def _closed_loop_review | 函数 | order, rt, positions, cash | 🔄 动作闭环审议 — 每个操盘动作先跑一轮闭环再决议

六步闭环:
  ① 模拟 |
| ai_sandbox_tick_engine.p | def _finance_committee_revie | 函数 | stats, trades, positions, rt,  | 🏛️ 金融委员会审议 + Eigenflux 专家会诊

从 DB 拉真实专家  |
| ai_sandbox_tick_engine.p | def _loss_recovery_rescue | 函数 | trades, positions, rt, review_ | 🚨 亏损挽救预案体系 — Loss Recovery Rescue System |
| ai_sandbox_tick_engine.p | def _execute_order | 函数 | order, rt, positions, trades_m | 执行单笔模拟下单 + 自动生成交易经验教训 |
| ai_sandbox_tick_engine.p | def _generate_trade_lesson | 函数 | action, sym, qty, price, rt, o | 🆕 自动生成单笔交易的经验教训 (规则-based, 复盘喂脑库用) |
| ai_sandbox_tick_engine.p | def _persist_review_session | 函数 | session | 复盘会话留档 → JSONL + 协作总线事件 |
| ai_sandbox_tick_engine.p | def _persist_meeting | 函数 | m | 单场会议记录留档 → JSONL (全局唯一 id, 溯源链) |
| ai_sandbox_tick_engine.p | def _gen_meetings | 函数 | review_type, stats, trades, po | 生成 5 层会议颗粒度 — 每场会议独立角色、独立议题、独立结论
meeting |
| ai_sandbox_tick_engine.p | def run_review_session | 函数 | review_type | 复盘会话 — noon (午间) / close (收市)
统一入口, 内部分  |
| ai_sandbox_tick_engine.p | def run_daily_review | 函数 |  | 兼容旧 API — 默认触发收市复盘 (close) |
| ai_sandbox_tick_engine.p | def _run_finance_audit | 函数 |  | 收市金融合规审计 (tick_engine 内置版, 与 sandbox_bp. |
| ai_sandbox_tick_engine.p | def _generate_period_report | 函数 | period | 生成周期汇总报告 (week / quarter / year) — 由 _re |
| ai_sandbox_tick_engine.p | def _archive_period_report | 函数 | period, key, report | 把周期报告 JSON 归档到 _runtime/ + 写 mt_finance_ |
| ai_sandbox_tick_engine.p | def _review_scheduler | 函数 |  | 复盘 + 审计 + 周期报表定时器
── 交易中日常 ──
  11:31~12 |
| ai_sandbox_tick_engine.p | def _daily_review_scheduler | 函数 |  | 兼容旧 API — 内部委托给 _review_scheduler |
| ai_sandbox_tick_engine.p | def _offline_learning_schedu | 函数 |  | 休市期间学习循环:
  - 交易时段: 不跑 (避免和实盘 tick 抢资源)
 |
| ai_sandbox_tick_engine.p | def _acquire_single_lock | 函数 |  | 进程级单实例锁 — 防止 launchd 守护进程与 modular_start |
| ai_sandbox_tick_engine.p | def start_sandbox_tick | 函数 | interval | 启动沙盘 tick daemon + 收市复盘定时器 + 休市学习循环 |
| ai_stock_sandbox_engine. | **class MarketDataProvider** | 类 | | 市场数据提供者 (双路: 真实新浪 + 模拟行情兜底)

真实行情: https |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def invalidate_cache | 方法 | self | 清缓存 (回测每天调一次, 强制重新拉/生成行情) |
| | ↳ def apply_daily_perturbation | 方法 | self, day, volatility | 给缓存里的行情注入日波动 (模拟回测专用)
- 首日以真实行情为锚点
- 后续每 |
| | ↳ def fetch_realtime | 方法 | self, secids | 拉取新浪实时行情 → {secid: {price, prev_close, o |
| | ↳ def _generate_simulation | 方法 | self, secids, seed_based | 模拟行情生成器 (新浪不可用时兜底)
用随机游走 + 板块联动 + 大盘惯性 |
| | ↳ def _ensure_history_cache | 方法 | self, db_path | 确保历史 K 线本地缓存表存在 |
| | ↳ def _secid_to_baostock | 方法 | self, secid | secid 格式转换: sh600519 → sh.600519, sz3007 |
| | ↳ def _secid_to_akshare | 方法 | self, secid | secid → AKShare 格式: sh600519 → 600519 |
| | ↳ def fetch_history_baostock | 方法 | self, secid, start_date, end_d | 拉取 baostock 历史日线 (真实数据, 免费无限流, 前复权)

返回: |
| | ↳ def fetch_history_akshare | 方法 | self, secid, start_date, end_d | 降级: AKShare 历史日线 (非东方财富源, 限流风险较低) |
| | ↳ def fetch_history_batch | 方法 | self, secids, start_date, end_ | 批量拉取历史日线 (baostock 主源 → AKShare 降级 → 显式  |
| | ↳ def _generate_fallback_histo | 方法 | self, secid, start_date, end_d | 最终降级 (所有真实源都不可用时): 生成一段 flat 行情
⚠️ 显式 so |
| | ↳ def apply_history_bar_to_cac | 方法 | self, secid, name, open_p, hig | 把某根历史 K 线灌入 self._cache (让 run_tick 内 fe |
| | ↳ def get_history_trade_dates | 方法 | self, history_dict | 从批量历史里提取所有交易日 (取第一只股票的日期作为基准) |
| ai_stock_sandbox_engine. | **class SandboxPortfolio** | 类 | | 沙盘组合 — 管理现金/持仓/交易/风控
支持多 session (一周/一年/ |
| | ↳ def __init__ | 方法 | self, scenario, days, initial_ |  |
| | ↳ def from_row | 方法 | cls, row | 从 DB 行恢复组合 — daemon 重启后必须接着原 session 跑,  |
| | ↳ def _save_portfolio | 方法 | self |  |
| | ↳ def get_total_value | 方法 | self, price_map | 当前总净值 = 现金 + 持仓市值 |
| | ↳ def get_position | 方法 | self, symbol |  |
| | ↳ def buy | 方法 | self, symbol, stock_name, pric | 买入 — 1/3 仓位分批买入, 最小 100 股
返回: trade dict |
| | ↳ def sell | 方法 | self, symbol, stock_name, pric | 卖出 — 全部持仓或指定股数

⚠️ A 股 T+1 结算规则:
T 日(交易日 |
| | ↳ def _insert_trade | 方法 | self, trade | 写入 mt_sandbox_trades, 同时双写到 mt_trade_log |
| | ↳ def check_risk_floor | 方法 | self, price_map | 风控检查 — 每日收盘后调用 |
| | ↳ def take_snapshot | 方法 | self, price_map, notes | 每日快照 |
| ai_stock_sandbox_engine. | **class StockSandboxEngine** | 类 | | 股市沙盘主控 — 定时 + 事件双驱动

用法:
  python3 -c "
 |
| | ↳ def __new__ | 方法 | cls |  |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def get_active_portfolio | 方法 | self, scenario | 获取当前活跃沙盘 (不存在则新建) |
| | ↳ def _is_a_stock_trading_day | 方法 | self, dt | 判断今天是不是 A 股交易日 (周末 + 法定假日 = False)
2026  |
| | ↳ def run_tick | 方法 | self | 一次 tick: 拉行情 → 跑 5 策略 → 团队投票 → 执行
注意: 周末 |
| | ↳ def _save_signal | 方法 | self, session_id, symbol, name |  |
| | ↳ def _feed_brain_after_tick | 方法 | self, session_id, results, tot | 每次 run_tick 后自动把所有有价值的信息喂进脑库

投喂内容:
  1. |
| | ↳ def simulate_days | 方法 | self, days, scenario | 快速模拟 N 个交易日 (自动 tick + 快照)
适合回测一周/一年 |
| | ↳ def simulate_week | 方法 | self | 一周快速模拟 |
| | ↳ def simulate_year | 方法 | self | 一年模拟 |
| | ↳ def simulate_history | 方法 | self, secids, start_date, end_ | 按真实历史 K 线逐日回放 (baostock 主源)

每一步:
  1. 加 |
| | ↳ def _publish_history_day_eve | 方法 | self, session_id, trade_date,  | 协作总线: 每个历史 tick 后 publish SANDBOX_HISTOR |
| | ↳ def _publish_history_complet | 方法 | self, report | 回测完成后 publish 最终报告 |
| | ↳ def start_daemon | 方法 | self, interval | 守护进程: 每 30s 一次 tick
同时监听协作总线 MARKET_ANOM |
| | ↳ def stop_daemon | 方法 | self |  |
| ai_stock_sandbox_engine. | def _conn | 函数 |  |  |
| ai_stock_sandbox_engine. | def _now_iso | 函数 |  |  |
| ai_stock_sandbox_engine. | def _gen_id | 函数 | prefix |  |
| ai_stock_sandbox_engine. | def ensure_sandbox_tables | 函数 |  | 初始化沙盘 5 张核心表 |
| ai_stock_sandbox_engine. | def strategy_momentum_breako | 函数 | quote, **kwargs | 动量突破 (超短线)
信号: 涨幅 > 2% + 放量 (成交量 > 昨日均量  |
| ai_stock_sandbox_engine. | def strategy_mean_reversion | 函数 | quote, **kwargs | 均值回归 (短线)
信号: 跌幅 > 5% 且超卖 (RSI<30 近似用跌幅判 |
| ai_stock_sandbox_engine. | def strategy_trend_following | 函数 | quote, **kwargs | 趋势跟随 (中线)
信号: 日内强趋势 + 成交量配合 |
| ai_stock_sandbox_engine. | def strategy_fundamental_val | 函数 | quote, **kwargs | 价值投资 (长线) — 日内简化版
信号: 高安全边际 + 长期基本面 (日内用 |
| ai_stock_sandbox_engine. | def strategy_panel_effect | 函数 | quote, market_quotes, **kwargs | 板块联动 — 同板块多只同时异动 |
| ai_stock_sandbox_engine. | def team_vote | 函数 | signals, quote, portfolio | 团队投票 → 最终决策
signals: [{strategy, signal_ |
| ai_stock_sandbox_engine. | def get_stock_sandbox | 函数 |  |  |
| ai_team_collab_engine.py | def _db | 函数 |  |  |
| ai_team_collab_engine.py | def init_tables | 函数 |  |  |
| ai_team_collab_engine.py | def _teams | 函数 | conn |  |
| ai_team_collab_engine.py | def match_teams | 函数 | text, limit | 按关键词命中数把任务分给最相关的天团 |
| ai_team_collab_engine.py | def _experts | 函数 | conn, host_team, limit |  |
| ai_team_collab_engine.py | def open_channel | 函数 | hall_task | 为一个任务大厅任务开协作频道, 拉齐多方参与者 |
| ai_team_collab_engine.py | def backfill | 函数 | limit | 把任务大厅在办任务全部开频道 |
| ai_team_collab_engine.py | def _render | 函数 | msg_type, actor, task, ctx |  |
| ai_team_collab_engine.py | def _broadcast | 函数 | conn, src_cid, msg_id, msg_typ | 把有价值的建议/猜想广播到**同领域**的其他频道, 防止闭门造车。
只投同 d |
| ai_team_collab_engine.py | def _feed_brain | 函数 | conn, content, actor |  |
| ai_team_collab_engine.py | def pulse | 函数 | batch, center_wave | 推进一轮交流: 优先让最沉默的成员发声, 🆕 center_wave=中心专属波 |
| ai_team_collab_engine.py | def status | 函数 |  |  |
| ai_team_collab_engine.py | def main | 函数 |  |  |
| auto_dev_team_engine.py | **class FeatureGap** | 类 | | 功能缺失项 |
| auto_dev_team_engine.py | **class DevLifecycleReport** | 类 | | 开发生命周期报告 |
| auto_dev_team_engine.py | **class GapScanner** | 类 | | 扫描系统中未开发功能和功能异常 |
| | ↳ def __init__ | 方法 | self, scan_dir |  |
| | ↳ def _log | 方法 | self, event, detail |  |
| | ↳ def scan_all | 方法 | self | 执行全量扫描 |
| | ↳ def _scan_route_placeholders | 方法 | self | 扫描路由中的占位符实现 |
| | ↳ def _scan_other_files_placeh | 方法 | self | 扫描其他Python文件中的占位符 |
| | ↳ def _extract_route_functions | 方法 | self, source | 提取路由与函数名的映射 |
| | ↳ def _get_return_value_str | 方法 | self, node | 获取return语句的值字符串 |
| | ↳ def _scan_todo_fixme | 方法 | self | 扫描代码中的TODO/FIXME标记 |
| | ↳ def _scan_missing_crud | 方法 | self | 扫描缺失的CRUD操作 |
| | ↳ def _scan_orphan_routes | 方法 | self | 扫描孤儿路由(路由存在但功能不完整) |
| | ↳ def _scan_frontend_backend_m | 方法 | self | 扫描前端引用但后端未实现的API |
| | ↳ def _is_route_function | 方法 | self, source, func_name | 检查函数是否是路由函数 |
| | ↳ def _get_route_for_func | 方法 | self, source, func_name | 获取函数对应的路由 |
| | ↳ def _create_gap | 方法 | self, gap_type, title, descrip | 创建功能缺失项 |
| auto_dev_team_engine.py | **class DevTaskDispatcher** | 类 | | 将功能缺失项派发到对应的开发团队 |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def _log | 方法 | self, event, detail |  |
| | ↳ def dispatch | 方法 | self, gaps | 派发所有缺失项 |
| | ↳ def _route_to_team | 方法 | self, gap | 根据功能缺失类型路由到对应团队 |
| auto_dev_team_engine.py | **class DevProgressTracker** | 类 | | 跟踪开发进度 |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def _log | 方法 | self, event, detail |  |
| | ↳ def start_development | 方法 | self, gaps | 开始开发 |
| | ↳ def code_review | 方法 | self, gaps | 代码评审 |
| | ↳ def testing | 方法 | self, gaps | 测试阶段 |
| | ↳ def complete | 方法 | self, gaps | 完成开发 |
| | ↳ def _generate_fix_snippet | 方法 | self, gap | 生成修复代码片段 |
| | ↳ def _fix_placeholder | 方法 | self, gap | 修复占位符 |
| | ↳ def _fix_crud | 方法 | self, gap | 修复缺失CRUD |
| | ↳ def _fix_api | 方法 | self, gap | 修复缺失API |
| | ↳ def _fix_route | 方法 | self, gap | 修复路由异常 |
| | ↳ def _fix_todo | 方法 | self, gap | 处理TODO/FIXME |
| auto_dev_team_engine.py | **class CompletionVerifier** | 类 | | 验证开发是否完成 |
| | ↳ def __init__ | 方法 | self, scan_dir |  |
| | ↳ def _log | 方法 | self, event, detail |  |
| | ↳ def verify | 方法 | self, gaps | 验证所有已完成项 |
| | ↳ def _verify_single | 方法 | self, gap | 验证单个功能项 |
| | ↳ def _verify_app_route | 方法 | self, gap | 验证app.py中的路由 |
| | ↳ def _verify_file_content | 方法 | self, gap | 验证文件内容 |
| | ↳ def _is_real_todo | 方法 | self, source, line_num | 判断指定行的TODO是否是真实的（非模板/字符串中的） |
| auto_dev_team_engine.py | **class FullReportGenerator** | 类 | | 生成全生命周期报告 |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def generate | 方法 | self, gaps, flow_id | 生成报告 |
| | ↳ def _build_gap_timeline | 方法 | self, gap | 构建单个gap的时间线 |
| | ↳ def _gap_to_dict | 方法 | self, gap | 转换为字典 |
| | ↳ def _build_summary | 方法 | self, status_counts, teams, ga | 构建摘要 |
| auto_dev_team_engine.py | **class AutoDevTeamEngine** | 类 | | 自动巡检队伍引擎 |
| | ↳ def __init__ | 方法 | self, scan_dir |  |
| | ↳ def run_full_cycle | 方法 | self, flow_id | 执行完整的巡检周期 |
| | ↳ def _persist_to_database | 方法 | self, flow_id | 持久化到数据库 |
| | ↳ def get_gaps | 方法 | self | 获取所有功能缺失项 |
| | ↳ def get_report | 方法 | self | 获取报告 |
| auto_dev_team_engine.py | def ensure_dev_lifecycle_tab | 函数 |  | 确保开发生命周期相关表存在 |
| galaxy_dyn_team_engine.p | **class RoleAssignment** | 类 | | 一个 AI 员工职能 → 视频生产中的职责 |
| galaxy_dyn_team_engine.p | **class AICrewMember** | 类 | |  |
| | ↳ def to_dict | 方法 | self |  |
| galaxy_dyn_team_engine.p | def _db | 函数 |  |  |
| galaxy_dyn_team_engine.p | def sample_by_neuralhub_task | 函数 | task, count | 从 DB 随机抽取 neuralhub_task 匹配的 AI 员工 |
| galaxy_dyn_team_engine.p | def assemble_dynamic_crew | 函数 | topic, team_size, preferred_ph | 按 RoleAssignment 动态组装 AI 员工团队

Args:
    |
| galaxy_dyn_team_engine.p | def crew_brief | 函数 | crew, topic | 生成团队简报 (给用户看) |
| galaxy_dyn_team_engine.p | def simulate_crew_workflow | 函数 | crew, topic | 模拟 AI 团队协作全过程 (用本地 Ollama 驱动)

返回一个 prod |
| galaxy_dyn_team_engine.p | def crew_to_production_spec | 函数 | crew, topic, use_ollama | 让 AI 团队协作产出完整 production_spec → 渲染视频

流程 |
| galaxy_dyn_team_engine.p | def _print_roster | 函数 |  | 打印全部可组合职能 (ROLE_ASSIGNMENTS 清单) |
| galaxy_dyn_team_engine.p | def main | 函数 |  |  |
| gobelin_adapter.py | def get_db_path | 函数 |  | 权威 DB 路径 |
| gobelin_adapter.py | def get_conn | 函数 |  | 返回带 Row 的 sqlite3 连接 |
| gobelin_adapter.py | def is_trading_hours | 函数 |  | 判断 A 股是否在交易时段 (简化版: 周一-周五 9:30-11:30 / 1 |
| gobelin_adapter.py | def _build_live_map | 函数 | conn | 拉 mt_live_position 全表 dict |
| gobelin_adapter.py | def _build_gp_map | 函数 | conn | 拉 mt_gobelin_price 全表 dict |
| gobelin_adapter.py | def get_price | 函数 | conn, symbol | 统一取价 — 适配层核心
返回 dict: {price, source_lab |
| gobelin_adapter.py | def get_account | 函数 | conn | Gobelin 主账户 (mt_gobelin_account WHERE ac |
| gobelin_adapter.py | def get_positions | 函数 | conn | Gobelin 持仓列表 (mt_gobelin_position WHERE  |
| gobelin_adapter.py | def get_account_and_position | 函数 | conn | 一次性获取账户 + 持仓 + 渠道聚合 (Flask 路由最常用) |
| gobelin_adapter.py | def get_channel_detail | 函数 | conn, channel_code | 单渠道详情 (/governance/channel/<code> 路由用) |
| gobelin_community_fusion | def _now | 函数 |  |  |
| gobelin_community_fusion | def _db | 函数 |  |  |
| gobelin_community_fusion | def _ensure_engines_path | 函数 |  | 确保 engines 目录在 sys.path 里 |
| gobelin_community_fusion | def _conn | 函数 |  |  |
| gobelin_community_fusion | def fuse_parliament_to_emplo | 函数 | conn, verbose | 把 25 席议员实体化到 mt_ai_employees |
| gobelin_community_fusion | def fuse_seal_to_employees | 函数 | conn, verbose | 把 4 个公章绑定到具体 AI 员工 |
| gobelin_community_fusion | def assign_guardian_findings | 函数 | conn, verbose | 📋 把 Guardian 最近的主动发现 → 派单给相关 AI 员工
- Fla |
| gobelin_community_fusion | def fuse_knowledge_to_traini | 函数 | conn, verbose | 🎓 把 KnowledgeBridge 反推 insight → 自动写入培训任 |
| gobelin_community_fusion | def fuse_execution_to_calibr | 函数 | conn, verbose | 📊 把 Gobelin 真实执行结果 → 反推校正 AI 员工能力等级
- 成功 |
| gobelin_community_fusion | def full_fusion | 函数 | verbose | 一键融合所有引擎到 AI 社区 |
| gobelin_community_fusion | def fusion_status | 函数 | conn | 融合状态检查 |
| gobelin_daily_pnl.py | **class GobelinDailyPnl** | 类 | | Gobelin 每日 PnL — 统一引擎接口 (BaseEngine 兼容) |
| | ↳ def __init__ | 方法 | self, db_path |  |
| | ↳ def start | 方法 | self |  |
| | ↳ def stop | 方法 | self |  |
| | ↳ def run_loop_once | 方法 | self |  |
| | ↳ def run_loop | 方法 | self, interval |  |
| | ↳ def emit_event | 方法 | self, event_name, target, payl |  |
| | ↳ def health_check | 方法 | self |  |
| gobelin_daily_pnl.py | def log | 函数 | msg |  |
| gobelin_daily_pnl.py | def is_trading_day | 函数 |  |  |
| gobelin_daily_pnl.py | def _fetch_realtime_prices | 函数 | symbols | 尝试通过 MarketDataService 获取实时价格, fallback  |
| gobelin_daily_pnl.py | def _calc_portfolio_position | 函数 | conn, session_id | 从 portfolio.positions_json + 实时价计算 posit |
| gobelin_daily_pnl.py | def run | 函数 |  |  |
| gobelin_guardian.py | def _now | 函数 |  |  |
| gobelin_guardian.py | def _db | 函数 |  |  |
| gobelin_guardian.py | def _conn | 函数 |  |  |
| gobelin_guardian.py | def _ensure_experience_table | 函数 | conn | 确保 AI 经验沉淀表存在 (幂等) |
| gobelin_guardian.py | def _log_reflect | 函数 | conn, rtype, subject, root, fi | 写一条反省记录 — 经验自动沉淀回库 |
| gobelin_guardian.py | def _learn_from_library | 函数 | conn, query_keyword, limit | 从经验库读取相关历史教训 (反省学习制) |
| gobelin_guardian.py | def refresh_gobelin_prices | 函数 | verbose |  |
| gobelin_guardian.py | def check_and_fix_consistenc | 函数 | verbose |  |
| gobelin_guardian.py | def cleanup_expired_and_arch | 函数 | verbose |  |
| gobelin_guardian.py | def proactive_discovery | 函数 | verbose | 🤔 自问自答式主动扫描 — 不等用户问, 自动发现问题
每个发现: 自动根因 + |
| gobelin_guardian.py | def run_reflect_cycle | 函数 | verbose |  |
| gobelin_guardian.py | def run_daemon | 函数 | interval_sec |  |
| gobelin_scheduler.py | **class GobelinScheduler** | 类 | | Gobelin Bank 调度引擎 — 行业标准交易时段.
三重门: is_tr |
| | ↳ def __init__ | 方法 | self, now, db_path |  |
| | ↳ def weekday | 方法 | self |  |
| | ↳ def is_workday | 方法 | self |  |
| | ↳ def time_str | 方法 | self |  |
| | ↳ def channel_in_session | 方法 | self, channel |  |
| | ↳ def active_channels | 方法 | self |  |
| | ↳ def next_meetings | 方法 | self, hours_ahead | 未来 hours_ahead 小时内要开的会议 |
| | ↳ def current_meeting | 方法 | self | 当前时间应该触发的会议类型 |
| | ↳ def _is_interval_due | 方法 | self, interval, range_start | 判断 interval 型会议是否应该触发 (每 interval 分钟) |
| | ↳ def execute_meeting | 方法 | self, meeting_code | 执行指定会议, 返回结果 |
| | ↳ def status | 方法 | self |  |
| gobelin_scheduler.py | def _time_in_range | 函数 | cur, start, end | 判断 cur(HH:MM) 是否在 [start, end] 区间 (支持 st |
| gobelin_scheduler.py | def _default_db | 函数 |  |  |
| gobelin_scheduler.py | def _ensure_scheduler_tables | 函数 | conn |  |
| gobelin_scheduler.py | def run_daemon | 函数 | interval_sec | 常驻调度守护进程: 每 interval_sec 秒检查一次是否有会议要开 |
| lab_sandbox_engine.py | **class _IsolationViolation** | 类 | |  |
| lab_sandbox_engine.py | **class _SafeConnWrapper** | 类 | | 包装 sqlite3.Connection, 在 execute 前做隔离检查  |
| | ↳ def __init__ | 方法 | self, real_conn |  |
| | ↳ def execute | 方法 | self, sql, params |  |
| | ↳ def executemany | 方法 | self, sql, seq |  |
| | ↳ def __getattr__ | 方法 | self, name |  |
| lab_sandbox_engine.py | **class LabSandboxEngine** | 类 | | 🧪 隔离实验学习沙盘 |
| | ↳ def __init__ | 方法 | self, db_path, check_isolation |  |
| | ↳ def ollama_ok | 方法 | self |  |
| | ↳ def quote_ok | 方法 | self |  |
| | ↳ def _check_ollama | 方法 | self |  |
| | ↳ def _check_quote | 方法 | self |  |
| | ↳ def init_db | 方法 | self |  |
| | ↳ def _ensure_brain_tables | 方法 | self, conn | 幂等确保脑库写入目标表存在 |
| | ↳ def create_experiment | 方法 | self, title, exp_type, initial |  |
| | ↳ def auto_join_all_active_ai_ | 方法 | self, conn, exp_id, initial_ca | 从 mtscos_ai_employees 或旧表 mt_ai_employee |
| | ↳ def _fallback_ai_seeds | 方法 | self | 兜底 AI 员工种子 (36 个) |
| | ↳ def _count_participants | 方法 | self, conn, exp_id |  |
| | ↳ def join_experiment | 方法 | self, exp_id, name, role, init |  |
| | ↳ def place_trade | 方法 | self, exp_id, part_id, symbol, | 模拟下单 + 腾讯行情 + AI 点评 + 资金/组合更新 |
| | ↳ def run_experiment_review | 方法 | self, exp_id |  |
| | ↳ def _calc_metrics | 方法 | self, trades, participants | 计算简易绩效指标 (胜率/盈亏比/Sharpe/MaxDD) |
| lab_sandbox_engine.py | def _get_db_path | 函数 |  | 优先 MTSCOS_DB_PATH env, 否则 flask-app/data |
| lab_sandbox_engine.py | def _isolation_check_sql | 函数 | sql | 检查 SQL 里是否含有真实交易表名 |
| lab_sandbox_engine.py | def _open_conn | 函数 | extra_safe, timeout | 打开沙盒 DB 连接, 默认启用表级隔离安全网

Args:
    extra |
| lab_sandbox_engine.py | def ensure_lab_tables | 函数 | conn | 幂等建表 + 索引 |
| lab_sandbox_engine.py | def _make_id | 函数 | prefix |  |
| lab_sandbox_engine.py | def get_realtime_quote | 函数 | symbol, timeout | 拉取腾讯行情, 解析返回; 失败返回 error 字段 |
| lab_sandbox_engine.py | def call_ollama | 函数 | prompt, system, timeout | 调用 Ollama, 返回生成文本; 失败返回空字符串 |
| lab_sandbox_engine.py | def ollama_trade_feedback | 函数 | trade, quote, exp_context | 实时点评一笔交易 |
| lab_sandbox_engine.py | def ollama_review | 函数 | experiment, trades, participan | AI 复盘整个实验 |
| lab_sandbox_engine.py | def ollama_extract_lessons | 函数 | review_text, trades_count, win | 从复盘文本 + 指标中提取可写入脑库的教训 (3-8 条) |
| lab_sandbox_engine.py | def _cli | 函数 |  |  |
| sandbox_bp.py | def _cached_realtime | 函数 |  | 带缓存的 _load_realtime() — 30s 内重复调用直接返回 |
| sandbox_bp.py | def _get_db | 函数 |  |  |
| sandbox_bp.py | def api_account | 函数 |  | 账户状态 — 本金/现金/持仓市值/总资产/盈亏/手续费 |
| sandbox_bp.py | def api_positions | 函数 |  | 当前持仓 — 带实时行情 |
| sandbox_bp.py | def api_trades | 函数 |  | 今日交易流水 (mt_trade_log) — 带 realized_pnl 自 |
| sandbox_bp.py | def api_decisions | 函数 |  | 决策流水 — 从 JSONL 文件读最新 N 条 |
| sandbox_bp.py | def api_trades_jsonl | 函数 |  | 交易复盘日志 (含自动生成的经验教训) |
| sandbox_bp.py | def api_radar | 函数 |  | 实时行情 + 异动汇总 |
| sandbox_bp.py | def api_events | 函数 |  | 实时事件 — 从协作总线读今日事件, 去重清洗后返回 |
| sandbox_bp.py | def _sina_daily_kline | 函数 | secid, days | 新浪日线 K 线 — 给 MDS 没有的自选股补数据
secid: sh6000 |
| sandbox_bp.py | def api_kline | 函数 |  | K线数据 — 大盘 + 自选池
?symbol=000001 只返回上证
?da |
| sandbox_bp.py | def api_status | 函数 |  | 系统状态 — daemon + Flask + DB + heartbeat ( |
| sandbox_bp.py | def api_review | 函数 |  | 今日复盘 — 从协作总线 + SQLite 复盘会话表取 (含 5 层会议详情) |
| sandbox_bp.py | def api_trigger_review | 函数 |  | 手动触发复盘 — review_type: 'noon' / 'close' / |
| sandbox_bp.py | def _run_eng_review | 函数 | review_type | 隔离 wrapper — 避免 Flask 主路由内调用阻塞 |
| sandbox_bp.py | def register_sandbox_bp | 函数 | app | 蓝图注册 + / 根路径 host-gated (stock.mtos.site |
| shield_daemon.py | def log | 函数 | msg |  |
| shield_daemon.py | def cycle | 函数 |  |  |
| shield_daemon.py | def main | 函数 |  |  |
| shield_inject_middleware | def inject_shield | 函数 | app | 主入口 — 在 Flask app 上调用一次，注入所有金盾保护 |
| shield_inject_middleware | def _inject_andromeda | 函数 | app | 仙女座: 会话创建 → 结束 → 脑库 → 金盾审计 全链路 |
| shield_inject_middleware | def _inject_iceberg | 函数 | app | 冰山: hall_tick → 金盾情报注入 + 提案闭环 → 海关合规 |
| shield_inject_middleware | def _inject_hall_security | 函数 | app | 大厅提案 4 件套安全注入 |
| shield_inject_middleware | def _inject_center_awareness | 函数 | app | 30 中心全量识别: before_request 匹配 URL → 标注 ce |
| shield_inject_middleware | def _inject_collab_bus | 函数 | app | 协同总线 ↔ 金盾总线 双向镜像 |
| shield_inject_middleware | def _get_db | 函数 |  |  |
| shield_inject_middleware | def _shield_audit_event | 函数 | event_type, source, target, se | 快速写金盾审计 (不阻塞, 不抛异常) |
| shield_inject_middleware | def _shield_iceberg_dispatch | 函数 | event_id, event_type, source,  | 快速触发冰山入厅 (写 hall_queue.jsonl) |
| shield_inject_middleware | def _shield_pending_for_iceb | 函数 |  | 冰山 tick 前: 拉取金盾待注入事件 |
| shield_inject_middleware | def _quick_customs_check | 函数 | actor, target, action | 海关总署快速合规检查 — 返回 0-100 风险分 |
| simulation_sandbox_engin | **class ActorPool** | 类 | |  |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def _build | 方法 | self |  |
| | ↳ def sample | 方法 | self, scenario_code, k |  |
| simulation_sandbox_engin | **class ScenarioEngine** | 类 | |  |
| | ↳ def list_scenarios | 方法 | self |  |
| | ↳ def build_context | 方法 | self, scenario_code |  |
| simulation_sandbox_engin | **class ActorAgent** | 类 | |  |
| | ↳ def speak | 方法 | actor, scenario_preset, ctx, t |  |
| simulation_sandbox_engin | **class MultiTurnDiscussionEngin** | 类 | |  |
| | ↳ def __init__ | 方法 | self, scenario_preset, context |  |
| | ↳ def _consensus | 方法 | self |  |
| | ↳ def run | 方法 | self |  |
| | ↳ def _synthesize_outcomes | 方法 | self |  |
| | ↳ def _ctx_summary | 方法 | self |  |
| simulation_sandbox_engin | **class PersistenceWriter** | 类 | |  |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def preset_require_consensus | 方法 | self |  |
| | ↳ def write_all | 方法 | self, session, messages, outco |  |
| simulation_sandbox_engin | **class SimulationSandboxEngine** | 类 | |  |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def run | 方法 | self, scenario_code, actor_cou |  |
| | ↳ def list_actors | 方法 | self, role, limit |  |
| simulation_sandbox_engin | def get_conn | 函数 |  |  |
| simulation_sandbox_engin | def get_ses_conn | 函数 |  |  |
| simulation_sandbox_engin | def ensure_tables | 函数 |  |  |
| simulation_sandbox_engin | def warmup | 函数 |  |  |
| simulation_sandbox_engin | def _cli | 函数 |  |  |
| teacher_sandbox_engine.p | **class TeacherSandboxEngine** | 类 | | 🎓 AI 教师学习团队沙盘引擎 |
| | ↳ def __init__ | 方法 | self, db_path |  |
| | ↳ def _open | 方法 | self | 每个方法内部调用, 线程安全 |
| | ↳ def create_team | 方法 | self, title, subject, team_typ |  |
| | ↳ def _auto_join_ai_teachers | 方法 | self, conn, team_id, subject | 自动加入 AI 教师 — 从 mt_ai_employees 取 active  |
| | ↳ def submit_lesson_plan | 方法 | self, team_id, teacher_id, tit |  |
| | ↳ def run_mock_class | 方法 | self, plan_id, team_id, teache |  |
| | ↳ def team_reflection | 方法 | self, team_id |  |
| | ↳ def get_team_status | 方法 | self, team_id |  |
| | ↳ def list_teams | 方法 | self, status, limit |  |
| | ↳ def close | 方法 | self |  |
| teacher_sandbox_engine.p | def _get_db_path | 函数 |  |  |
| teacher_sandbox_engine.p | def _isolation_check_sql | 函数 | sql |  |
| teacher_sandbox_engine.p | def _open_conn | 函数 | timeout |  |
| teacher_sandbox_engine.p | def _make_id | 函数 | prefix |  |
| teacher_sandbox_engine.p | def ensure_ts_tables | 函数 | conn | 幂等建表 + 索引 |
| teacher_sandbox_engine.p | def call_ollama | 函数 | prompt, system, timeout | 调用 Ollama, 返回生成文本 |
| teacher_sandbox_engine.p | def ollama_feedback_plan | 函数 | plan_title, grade, plan_conten | AI 导师从五维能力点评教案 |
| teacher_sandbox_engine.p | def ollama_mock_student | 函数 | plan_title, grade, plan_conten | AI 扮演某类学生, 输出课堂反应 |
| teacher_sandbox_engine.p | def ollama_team_reflection | 函数 | plans_summary, mock_summary | AI 对一组教案 + 模拟课堂结果做团队层面的教学反思 |
| teacher_sandbox_engine.p | def _cli | 函数 |  |  |
| trading_routes.py | def ollama_chat | 函数 | system_prompt, user_prompt, te | 真实 Ollama chat 调用。严格判定 error 字段 + HTTP 非 |
| trading_routes.py | def ollama_healthz | 函数 |  | Ollama 健康探针 (调用 /api/tags) |
| trading_routes.py | def run_ten_expert_ollama | 函数 | symbol, name, context | 10 专家 Ollama 并行会诊 (满运能并发, 禁止 mock 降级) |
| trading_routes.py | def _triple_lock | 函数 |  | 三重锁: IP → SA uid → VIKEY+SZU100 双硬件密钥
sa |
| trading_routes.py | def api_overview | 函数 |  | 仪表盘: 本金/市值/盈亏/胜率/指数/情绪面/风控门 (Fix 4: 从 DB |
| trading_routes.py | def api_candidates | 函数 |  | 候选清单 (Fix 5: 从 mt_sandbox_signals 读真实 BU |
| trading_routes.py | def api_suggest | 函数 |  | 触发十专家会诊 — 真实 Ollama 调用 (禁止 mock 降级) |
| trading_routes.py | def _lookup_stock_name | 函数 | symbol | 从 DB 查股票名 |
| trading_routes.py | def _build_context_for_symbo | 函数 | symbol | 从 DB 拉某 symbol 的上下文 (信号 + 持仓 + B股识别) |
| trading_routes.py | def _get_top_bull_signal | 函数 |  | 从 mt_sandbox_signals 拉 score>=70 的 BULL  |
| trading_routes.py | def api_order | 函数 |  | 下单 (paper trading → 入厅, 不真正交易) |
| trading_routes.py | def api_positions | 函数 |  |  |
| trading_routes.py | def api_risk_check | 函数 |  |  |
| trading_routes.py | def _risk_check | 函数 | symbol, action, price | R-06 风控官: 5%硬止损 + 20%仓位上限 |
| trading_routes.py | def api_review_daily | 函数 |  |  |
| trading_routes.py | def api_review_weekly | 函数 |  |  |
| trading_routes.py | def api_review_brain_bank | 函数 |  | 复盘 → mt_trading_experience_bank 脑库反噬 |
| trading_routes.py | def _review_generate | 函数 | period |  |
| trading_routes.py | def _check_review_daemon | 函数 |  | 复盘 daemon 是否在跑 |
| trading_routes.py | def api_hall_sync | 函数 |  | 读取大厅队列 / 写入大厅 |
| trading_routes.py | def api_ollama_health | 函数 |  | 前端探测真实 Ollama 是否可用 |
| trading_routes.py | def index | 函数 |  | 操盘控制台 (深金主题) |
| trading_routes.py | def _trading_console_html | 函数 |  |  |
| trading_routes.py | def _write_hall | 函数 | entry | 写入大厅 JSONL 队列 |
| trading_routes.py | def _read_last_hall_report | 函数 |  | 读取最近一条大厅记录 |
| trading_routes.py | def api_sandbox_data | 函数 |  | 沙盘一站式真实行情 (从 market_data_service) |
| trading_routes.py | def api_sandbox_suggest | 函数 |  | 沙盘推演复盘 → 真实 Ollama 十专家会诊 → 入厅 mt_lab_tas |
| trading_routes.py | def api_sandbox_order | 函数 |  | 沙盘模拟下单 → 入 mt_trade_log → 完结大厅任务 status= |
| trading_routes.py | def api_openclaw_proxy | 函数 | subpath | 反向代理 → Semantica REST server。

透传规则:
  - |
| trading_routes.py | def api_openclaw_health | 函数 |  | 快速健康检查 — 不依赖上游可达性 |
| trading_routes.py | def _generate_crowd_verdict | 函数 | symbol, name, review, experts | 十专家会诊 — 简化模拟 (后续接 Ollama) |
| trading_routes.py | def _expert_reason | 函数 | code, symbol, review |  |
| trading_routes.py | def _insert_hall_task | 函数 | payload | 直接 INSERT mt_lab_task_hall, 返回 id |
| trading_routes.py | def _complete_hall_task | 函数 | hall_code, trade_id | 完结大厅任务 → status=DONE, flow_node=SANDBOX_ |
| trading_routes.py | def _insert_trade_log | 函数 | trade | 写 mt_trade_log |
| trading_routes.py | def _insert_sandbox_trade | 函数 | session_id, trade_data | 写 mt_sandbox_trades (Fix 1: 统一交易写入) |
| trading_routes.py | def _rebuild_portfolio_posit | 函数 | session_id, db_path | 从 trades 重建 portfolio.positions_json (Fi |
| trading_routes.py | def _find_or_create_session_ | 函数 | db_path | 找到 RUNNING session, 如果没有就用 SB-e3105ea094 |
| trading_routes.py | def _find_flask_db | 函数 |  | 找到 Flask 实际使用的 DB 路径 (兼容多目录) |
<!-- AUTO-GENERATED-END:functions -->

## 6. 依赖关系
<!-- AUTO-GENERATED-START:deps -->
- 古灵阁 ← 冰山 (通过 collab_bus 接收阈值异常警报)
- 古灵阁 → 冰山 (交易裁决结果广播给五自系统)
- 古灵阁 → mt_collab_bus_events (团队协作总线事件)
- 古灵阁 → mt_sandbox_tick_log (沙盘心跳)
- 古灵阁 ← mt_asset_transactions (资产流水)
**扫描统计**: 39 模块 | 32 表 | 314 路由
<!-- AUTO-GENERATED-END:deps -->
