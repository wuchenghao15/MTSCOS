# 仙女座 Andromeda 系统说明

> 自动生成时间: 2026-11-11 19:08
> 系统哈希: cc43b66af4a60497... (变更时更新)
> 源码路径: engines/andromeda_self_heal.py, engines/andromeda_status_page.py, engines/andromeda_upgrade.py, engines/andromeda_auto_evolution.py, engines/andromeda_core.py

## 1. 系统概述
<!-- AUTO-GENERATED-START:overview -->
协作总线 (Collaboration Bus) — 多中心事件广播枢纽
══════════════════════════════════════════════════
flow: flow_collab_bus_20261102

## 架构
┌──────────────────────────────────────────────────────────────────┐
│                     CollabBus (Pub/Sub 单例)                      │
│  ┌──────────┐  publish  ┌──────────┐  subscribe  ┌─────────────┐ │
│  │ 市场雷达  │ ────────▶ │ 事件队列  │ ─────────▶ │  N 订阅者   │ │
│  │ (5s

**模块数**: 56 | **类**: 38 | **顶层函数**: 753
<!-- AUTO-GENERATED-END:overview -->

## 2. 架构图 (ASCII)
<!-- AUTO-GENERATED-START:arch -->
  ╔══════════════════════════════════════════════════════════╗
  ║  仙女座 Andromeda                                   ║
  ╠══════════════════════════════════════════════════════════╣
  ║                                                          ║
  ║  ┌─ 入口 API ──────────────────────────────────────────┐  ║
  ║  │  ANY /                                                 │  ║
  ║  │  ANY /andromeda                                        │  ║
  ║  │  ANY /andromeda/stats                                  │  ║
  ║  │  ANY /api/data                                         │  ║
  ║  │  ANY /api/employees                                    │  ║
  ║  └─────────────────────────────────────────────────────┘  ║
  ║                          │                               ║
  ║                          ▼                               ║
  ║  ┌─ 核心引擎 ──────────────────────────────────────────┐  ║
  ║  │  CollabSolidarityEngine                                │  ║
  ║  └─────────────────────────────────────────────────────┘  ║
  ║                          │                               ║
  ║                          ▼                               ║
  ║  ┌─ 数据库表 ──────────────────────────────────────────┐  ║
  ║  │  mt_ai_auto_hire_log                                   │  ║
  ║  │  mt_ai_brain_feed_log                                  │  ║
  ║  │  mt_ai_capability_registry                             │  ║
  ║  │  mt_ai_employee_skill                                  │  ║
  ║  │  mt_ai_employees                                       │  ║
  ║  │  mt_ai_experience_snippet                              │  ║
  ║  └─────────────────────────────────────────────────────┘  ║
  ║                                                          ║
  ╚══════════════════════════════════════════════════════════╝
<!-- AUTO-GENERATED-END:arch -->

## 3. API 端点
<!-- AUTO-GENERATED-START:api -->
| 蓝图 | 方法 | URL | 处理函数 | 说明 |
|------|------|-----|----------|------|
| andromeda_hu | ANY | /andromeda/hub | andromeda_hub_page | 🪐 仙女座总枢纽 — 四层全景页 (flow_andromeda_p4_2026 |
| andromeda_hu | ANY | /api/andromeda/hub | api_andromeda_hub |  |
| andromeda_op | ANY | /v1/chat/completions | chat_completions |  |
| andromeda_op | ANY | /v1/models | list_models |  |
| andromeda_op | ANY | /v1/responses | responses |  |
| andromeda_st | ANY | /andromeda/stats | stats_page |  |
| andromeda_st | ANY | /api/andromeda/stats/dispatch | stats_dispatch | 缺口 → 研发联动: 写入 smart_mount 建议池(mt_ai_sugg |
| andromeda_st | ANY | /api/andromeda/stats/events | stats_events |  |
| andromeda_st | ANY | /api/andromeda/stats/overview | stats_overview |  |
| app | ANY | / | get_data | 一次性返回所有状态数据 (前端 2.5s 轮询) |
| app | ANY | /andromeda | run |  |
| app | ANY | /api/data | get_data | 一次性返回所有状态数据 (前端 2.5s 轮询) |
| app | ANY | /api/employees | api_employees |  |
| app | ANY | /api/sync/push | api_sync_push | 真正的双向同步: upsert, 两边取并集 |
| app | ANY | /api/sync/refresh | api_sync_refresh | 清缓存 + 重新拉 mini_sync |
| auth_bp | ANY | /register |  |  |
| bp | ANY | /api/andromeda_daemon_status | api_andromeda_daemon | 守护进程状态 — PID / Ollama / daemon registry |
| bp | ANY | /api/copy_archive | api_copy_archive | 文案永久存档 (分页, 每页 20) |
| bp | ANY | /api/daemon_status | api_daemon_status |  |
| bp | ANY | /api/db_metrics | api_db_metrics | 核心表行数 + 24h 增量 |
| bp | ANY | /api/evolution_timeline | api_evolution_timeli | 11 阶段冰山演化时间线 + 全版本      schema 兼容: engin |
| bp | ANY | /api/iceberg/eigenflux | api_eigenflux | EigenFlux 专家团 + 真实 daemon |
| bp | ANY | /api/iceberg/health | api_iceberg_health | 真实健康度数据 — 心跳停摆标红 |
| bp | ANY | /api/iceberg/upgrade_board | api_upgrade_board | 升级报告数据 |
| bp | ANY | /api/iceberg_layer_stats | api_iceberg_layer_st | 知识脑库按冰山三层聚合 — 前端动态厚度数据源     v25.2: 主数据源切 |
| bp | ANY | /api/iceberg_structure | api_iceberg_structur | 冰山三层架构快照 |
| bp | ANY | /api/iol_summary | api_iol_summary | IOL 实时面板数据 — mt_iceberg_optimization_log |
| bp | ANY | /api/knowledge_brain/ask | api_knowledge_ask | 向 AI 人格请教 — 人格模板 + Ollama qwen2.5:7b 生成 |
| bp | ANY | /api/knowledge_brain/personas | api_knowledge_person | 知识贡献者人格档案列表 |
| bp | ANY | /api/knowledge_brain/search | api_knowledge_search | 知识脑库搜索 API — 支持关键词/领域/难度/平台 过滤 |
| bp | ANY | /api/knowledge_brain/semantic | api_knowledge_semant | 脑库语义检索 API (flow_andromeda_iceberg_20261 |
| bp | ANY | /api/knowledge_brain/stats | api_knowledge_stats | 知识脑库统计概览 |
| bp | ANY | /api/knowledge_graph/data | api_knowledge_graph_ | 🕸️ 知识图谱数据 (flow_redblue_ui_20261018: 修复页 |
| bp | ANY | /api/param/changelog | api_param_changelog | 变更审计链 (规范§6 留痕可溯) ?limit=50 |
| bp | ANY | /api/param/delete | api_param_delete | 删除参数 — 仅 super_admin + 审计留痕 |
| bp | ANY | /api/param/list | api_param_list | 参数清单 ?domain=ai  (is_secret=1 值脱敏) |
| bp | ANY | /api/param/scan | api_param_scan | 手动触发参数健康巡检 (登录可触发, 修改无需权限—只读扫描+落库) |
| bp | ANY | /api/param/set | api_param_set | 创建/修改参数 — 仅 super_admin (规范§6.1) |
| bp | ANY | /api/param/stats | api_param_stats | 参数体系总览: 域分布/类型分布/健康度/最近巡检 |
| bp | ANY | /api/persona_chat | api_persona_chat | 💬 AI 人格聊天室 — Ollama qwen2.5:7b + 脑库RAG + |
| bp | ANY | /api/persona_chat/history | api_persona_chat_his | 💬 persona_chat 会话历史回放 (flow_andromeda_ch |
| bp | ANY | /api/system_health | api_system_health | 一键健康检查 |
| bp | ANY | /api/twin_machine | api_twin_machine | Mac mini 健康状态 (需 ssh andromeda) |
| bp | ANY | /api/upgrade_overviews | api_upgrade_overview | 全部 7d 升级总览 |
| bp | ANY | /api/upgrade_reports | api_upgrade_reports | 最近 20 份 4h 升级报告 |
| bp | ANY | /api/wqx/generate | api_wqx_generate | 📜 文曲星生文 API — 调 ai_wenquxing_engine      |
| bp | ANY | /api/wqx/list | api_wqx_list | 历史任务列表 |
| bp | ANY | /api/wqx/task/<task_id> | api_wqx_task | 查询单个文曲星任务 |
| bp | ANY | /collapse_theorem | collapse_theorem_pag | PRIME_COLLAPSE_THEOREM 质因数递归坍缩7 可视化 |
| bp | ANY | /dashboard | dashboard_page | 仙女座仪表盘主页面 |
| bp | ANY | /eigenflux_council | eigenflux_council_pa | EigenFlux 专家团 + 天团矩阵 + AI 员工 |
| bp | ANY | /gray_center | gray_center_page | 灰度发布中心 (flow_secondary_pages_20261018: 主 |
| bp | ANY | /health_board | health_board_page | 🩺 冰山健康度仪表盘 — 真实心跳 + 停摆标红 + 坍缩锚点 |
| bp | ANY | /iceberg_center | iceberg_center_page | 🧊 冰山统一控制中心 — 三层动态厚度 + 知识脑库融合 + 导航 |
| bp | ANY | /iceberg_evolution | iceberg_evolution_pa | 冰山演化时间线前端 — 水墨赤壁赋 文人风 |
| bp | ANY | /iceberg_meta | iceberg_meta_page | 冰山元数据看板 (flow_secondary_pages_20261018:  |
| bp | ANY | /knowledge_brain | knowledge_brain_page | 仙女座知识脑库前端页面 (极暗星空风) |
| bp | ANY | /knowledge_graph | knowledge_graph_page | 🕸️ D3.js 知识图谱 力导向图 |
| bp | ANY | /param_center | param_center_page | ⚙️ 仙女座参数中心 — 统一参数体系面板 |
| bp | ANY | /persona_chat | persona_chat_page | 💬 AI 人格实时聊天室 — 多人格同时讨论 |
| bp | ANY | /stats/overview | stats_overview |  |
| bp | ANY | /upgrade_board | upgrade_board_page | 升级报告仪表盘 |
| bp | ANY | /wenquxing | wenquxing_page | 📜 文曲星 — 仙女座文学域 AI 写作生成器 (冰山内嵌) |
| chat_plus_bp | ANY | /api/local-chat/jump/center | chat_jump_center | 任务中心详情: 各状态任务数 + 近期任务 (任务大厅中心名可点击进入) |
| chat_plus_bp | ANY | /api/local-chat/jump/resolve | chat_jump_resolve | 把消息里的任务号 / @天团 / 会话号解析成可跳转目标 |
| chat_plus_bp | ANY | /api/local-chat/jump/task/<int:task_id> | chat_jump_task | 任务跳转详情: 基础信息 + 状态机轨迹 (供聊天面板内展示) |
| chat_plus_bp | ANY | /api/local-chat/jump/team | chat_jump_team | 天团详情: 名称/关键词/成员/近期承接任务 (供聊天面板内展示, 不跳空白页) |
| chat_plus_bp | ANY | /api/local-chat/mention | chat_mention | 把聊天里 @天团 的内容一键派成任务大厅任务, 并回帖系统消息 |
| chat_plus_bp | ANY | /api/local-chat/msg/<int:mid> | chat_msg_edit |  |
| chat_plus_bp | ANY | /api/local-chat/msg/<int:mid>/feedback | chat_msg_feedback |  |
| chat_plus_bp | ANY | /api/local-chat/msg/context | chat_msg_context | 按 mid 返回前后若干条消息, 供检索结果直接定位到具体消息 |
| chat_plus_bp | ANY | /api/local-chat/msg/list | chat_msg_list |  |
| chat_plus_bp | ANY | /api/local-chat/multi-ai | chat_multi_ai | 多人 AI 同时聊: 一条需求 → N 位 AI 并发作答 → 总控收敛 (可选 |
| chat_plus_bp | ANY | /api/local-chat/plus/meta | chat_plus_meta |  |
| chat_plus_bp | ANY | /api/local-chat/search | chat_search |  |
| chat_plus_bp | ANY | /api/local-chat/session/<sid>/archive | chat_session_archive |  |
| chat_plus_bp | ANY | /api/local-chat/session/<sid>/export | chat_export |  |
| chat_plus_bp | ANY | /api/local-chat/session/<sid>/read | chat_mark_read |  |
| chat_plus_bp | ANY | /api/local-chat/unread | chat_unread |  |
| collab_bp | ANY | /events | api_bus_events |  |

_（共 136 个端点,仅展示前 80 个）_
<!-- AUTO-GENERATED-END:api -->

## 4. 数据库表
<!-- AUTO-GENERATED-START:tables -->
### mt_ai_auto_hire_log (41 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| hire_id | TEXT | ✓ | 是 |
| hire_type | TEXT |  | 否 |
| employee_name | TEXT |  | 是 |
| employee_role | TEXT |  | 是 |
| source | TEXT |  | 是 |
| details_json | TEXT |  | 是 |
| hired_at | TEXT |  | 否 |

### mt_ai_brain_feed_log (64,129 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| feed_id | TEXT | ✓ | 是 |
| feed_type | TEXT |  | 否 |
| category | TEXT |  | 否 |
| source | TEXT |  | 否 |
| session_id | TEXT |  | 是 |
| symbol | TEXT |  | 是 |
| content | TEXT |  | 否 |
| score | REAL |  | 是 |
| is_correct | INTEGER |  | 是 |
| extra | TEXT |  | 是 |
| created_at | TEXT |  | 否 |
| brain_marked | INTEGER |  | 是 |

### mt_ai_capability_registry (400 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| cap_id | TEXT | ✓ | 是 |
| category | TEXT |  | 否 |
| capability_name | TEXT |  | 否 |
| source_file | TEXT |  | 是 |
| description | TEXT |  | 是 |
| parameters | TEXT |  | 是 |
| ollama_usage | INTEGER |  | 是 |
| enabled | INTEGER |  | 是 |
| health_score | REAL |  | 是 |
| last_used | TEXT |  | 是 |
| usage_count | INTEGER |  | 是 |
| success_rate | REAL |  | 是 |
| discovered_at | TEXT |  | 是 |

### mt_ai_employee_skill (146 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| employee_id | TEXT |  | 否 |
| skill_id | TEXT |  | 否 |
| proficiency | REAL |  | 是 |
| assigned_at | TEXT |  | 是 |

### mt_ai_employees (80 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| employee_id | TEXT | ✓ | 是 |
| name | TEXT |  | 否 |
| role | TEXT |  | 是 |
| center | TEXT |  | 是 |
| status | TEXT |  | 是 |
| level | REAL |  | 是 |
| scores_json | TEXT |  | 是 |
| skills_json | TEXT |  | 是 |
| avatar_emoji | TEXT |  | 是 |
| source | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_ai_experience_snippet (140 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| snippet_id | TEXT | ✓ | 是 |
| snippet_type | TEXT |  | 否 |
| domain | TEXT |  | 是 |
| context_summary | TEXT |  | 是 |
| action_taken | TEXT |  | 是 |
| outcome | TEXT |  | 是 |
| lesson_learnt | TEXT |  | 是 |
| confidence | REAL |  | 是 |
| source_log_ids | TEXT |  | 是 |
| applicable_engines | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| source_log_count | INTEGER |  | 是 |

### mt_ai_meta_cycle (3 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| cycle_id | TEXT | ✓ | 是 |
| cycle_time | TEXT |  | 是 |
| registry_count | INTEGER |  | 是 |
| routes_decided | INTEGER |  | 是 |
| workflows_composed | INTEGER |  | 是 |
| experiences_distilled | INTEGER |  | 是 |
| idle_improve_actions | INTEGER |  | 是 |
| ollama_calls | INTEGER |  | 是 |
| ollama_latency_ms | REAL |  | 是 |
| total_duration_ms | REAL |  | 是 |
| meta_score | REAL |  | 是 |
| created_at | TEXT |  | 是 |

### mt_ai_neural_prompt_versions (30 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| version_id | INTEGER | ✓ | 是 |
| task_name | TEXT |  | 否 |
| version_tag | TEXT |  | 否 |
| old_system_prompt | TEXT |  | 否 |
| new_system_prompt | TEXT |  | 否 |
| rationale | TEXT |  | 是 |
| trigger_type | TEXT |  | 是 |
| validator_ok | INTEGER |  | 是 |
| sanitized_ok | INTEGER |  | 是 |
| rate_limit_ok | INTEGER |  | 是 |
| applied | INTEGER |  | 是 |
| rollback_of | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_ai_neural_test_seeds (66 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| seed_id | INTEGER | ✓ | 是 |
| task_name | TEXT |  | 否 |
| seed_index | INTEGER |  | 否 |
| test_payload | TEXT |  | 否 |
| expect_nonempty | INTEGER |  | 是 |
| note | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_ai_route_decision (26 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| route_id | TEXT | ✓ | 是 |
| task | TEXT |  | 否 |
| context | TEXT |  | 是 |
| selected_engines | TEXT |  | 是 |
| reasoning | TEXT |  | 是 |
| confidence | REAL |  | 是 |
| fallback_used | INTEGER |  | 是 |
| switches_applied | TEXT |  | 是 |
| execution_duration_ms | REAL |  | 是 |
| success | INTEGER |  | 是 |
| experience_learnt | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_ai_workflow (5 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| workflow_id | TEXT | ✓ | 是 |
| task_template | TEXT |  | 否 |
| steps | TEXT |  | 否 |
| dag_graph | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| last_executed | TEXT |  | 是 |
| execution_count | INTEGER |  | 是 |
| avg_duration_ms | REAL |  | 是 |
| success_rate | REAL |  | 是 |

### mt_andromeda_contributor_persona (14 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| persona_id | INTEGER | ✓ | 是 |
| name | TEXT |  | 否 |
| type | TEXT |  | 是 |
| domain | TEXT |  | 是 |
| knowledge_summary | TEXT |  | 是 |
| thought_pattern | TEXT |  | 是 |
| question_template | TEXT |  | 是 |
| is_active | INTEGER |  | 是 |

### mt_andromeda_knowledge_base (175 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| k_id | INTEGER | ✓ | 是 |
| title | TEXT |  | 是 |
| domain | TEXT |  | 是 |
| source_platform | TEXT |  | 是 |
| source_url | TEXT |  | 是 |
| author_name | TEXT |  | 是 |
| author_profile_url | TEXT |  | 是 |
| difficulty_level | TEXT |  | 是 |
| play_count | INTEGER |  | 是 |
| duration_seconds | INTEGER |  | 是 |
| published_at | TEXT |  | 是 |
| ai_summary | TEXT |  | 是 |
| knowledge_points | TEXT |  | 是 |
| quality_score | REAL |  | 是 |
| collected_at | TEXT |  | 是 |

### mt_andromeda_workflow_runs (19 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| run_id | TEXT | ✓ | 是 |
| workflow_id | TEXT |  | 否 |
| trigger_source | TEXT |  | 是 |
| status | TEXT |  | 是 |
| input_json | TEXT |  | 是 |
| output_json | TEXT |  | 是 |
| stages_json | TEXT |  | 是 |
| tokens_input | INTEGER |  | 是 |
| tokens_output | INTEGER |  | 是 |
| llm_calls | INTEGER |  | 是 |
| wall_ms | INTEGER |  | 是 |
| cost_usd | REAL |  | 是 |
| revenue_usd | REAL |  | 是 |
| profit_usd | REAL |  | 是 |
| started_at | TEXT |  | 是 |
| finished_at | TEXT |  | 是 |
| error_msg | TEXT |  | 是 |

### mt_app_login_sessions (35 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| session_token | TEXT | ✓ | 是 |
| user_id | TEXT |  | 否 |
| username | TEXT |  | 否 |
| role | TEXT |  | 否 |
| user_ip | TEXT |  | 是 |
| user_agent | TEXT |  | 是 |
| expires_at | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_asset_accounts (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| account_no | TEXT |  | 否 |
| user_id | TEXT |  | 否 |
| username | TEXT |  | 是 |
| asset_type | TEXT |  | 否 |
| balance | INTEGER |  | 否 |
| frozen | INTEGER |  | 否 |
| credit_limit | INTEGER |  | 是 |
| status | TEXT |  | 否 |
| tier | TEXT |  | 是 |
| meta | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_asset_transactions (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| tx_hash | TEXT |  | 否 |
| from_account | TEXT |  | 是 |
| to_account | TEXT |  | 是 |
| asset_type | TEXT |  | 否 |
| amount | INTEGER |  | 否 |
| balance_after | INTEGER |  | 否 |
| tx_type | TEXT |  | 否 |
| status | TEXT |  | 否 |
| ref_id | TEXT |  | 是 |
| detail | TEXT |  | 是 |
| operator_id | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_autodev_derivatives (49 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| deriv_id | TEXT | ✓ | 是 |
| deriv_type | TEXT |  | 否 |
| source_ids | TEXT |  | 是 |
| content | TEXT |  | 是 |
| confidence | REAL |  | 是 |
| ic | REAL |  | 是 |
| backtest_sharpe | REAL |  | 是 |
| status | TEXT |  | 是 |
| registered_at | TEXT |  | 是 |
| performance | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_blockchain (339 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| height | INTEGER | ✓ | 是 |
| block_hash | TEXT |  | 否 |
| prev_hash | TEXT |  | 否 |
| timestamp | TEXT |  | 是 |
| tx_count | INTEGER |  | 是 |
| proposer | TEXT |  | 是 |
| validator_count | INTEGER |  | 是 |
| merkle_root | TEXT |  | 是 |
| data_json | TEXT |  | 是 |

### mt_brain_daily_stats (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| stat_date | TEXT | ✓ | 是 |
| total_feeds | INTEGER |  | 是 |
| edu_feeds | INTEGER |  | 是 |
| sandbox_feeds | INTEGER |  | 是 |
| system_feeds | INTEGER |  | 是 |
| sources_json | TEXT |  | 是 |
| notable_events | TEXT |  | 是 |
| updated_at | TEXT |  | 否 |

### mt_center_collab_matrix (647 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| matrix_id | TEXT | ✓ | 是 |
| source_center | TEXT |  | 否 |
| target_center | TEXT |  | 否 |
| event_count | INTEGER |  | 是 |
| last_collab | TEXT |  | 是 |
| event_types | TEXT |  | 是 |
| relationship | TEXT |  | 是 |
| suggested_upgrade | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_center_self_drive_log (40,365 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| log_id | INTEGER | ✓ | 是 |
| center_name | TEXT |  | 否 |
| action | TEXT |  | 否 |
| direction_id | INTEGER |  | 是 |
| task_hall_id | INTEGER |  | 是 |
| outcome | TEXT |  | 是 |
| duration_ms | INTEGER |  | 是 |
| detail | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_channel_policy_snapshot (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| snapshot_date | TEXT |  | 是 |
| channel | TEXT |  | 是 |
| policy_json | TEXT |  | 是 |
| policy_version | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_chat_model_pricing (8 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| model_id | TEXT | ✓ | 是 |
| display_name | TEXT |  | 否 |
| model_weight | REAL |  | 否 |
| prompt_per_1k | INTEGER |  | 否 |
| completion_per_1k | INTEGER |  | 否 |
| is_active | INTEGER |  | 否 |
| updated_at | TEXT |  | 是 |

### mt_chat_schedule (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| user_id | INTEGER |  | 否 |
| username | TEXT |  | 否 |
| title | TEXT |  | 否 |
| due_at | TEXT |  | 是 |
| session_id | TEXT |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| done_at | TEXT |  | 是 |

### mt_cnkr_track_log (610 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| cycle_no | INTEGER |  | 是 |
| action | TEXT |  | 否 |
| track | TEXT |  | 是 |
| input_count | INTEGER |  | 是 |
| output_count | INTEGER |  | 是 |
| detail | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_cnkr_tracks (15 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| track | TEXT |  | 否 |
| family | TEXT |  | 否 |
| family_en | TEXT |  | 是 |
| min_diff | INTEGER |  | 是 |
| max_diff | INTEGER |  | 是 |
| description | TEXT |  | 是 |
| target_count | INTEGER |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_collab_bus_events (8,549 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| event_id | TEXT | ✓ | 是 |
| event_type | TEXT |  | 否 |
| source | TEXT |  | 否 |
| severity | TEXT |  | 是 |
| symbol | TEXT |  | 是 |
| payload | TEXT |  | 是 |
| subscribers_json | TEXT |  | 是 |
| broadcast_ms | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |
| target_system | TEXT |  | 是 |
| status | TEXT |  | 是 |
| dispatched_at | TEXT |  | 是 |
| error | TEXT |  | 是 |
| event_name | TEXT |  | 是 |
| source_system | TEXT |  | 是 |

### mt_collab_bus_subscribers (12 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| subscriber_id | TEXT | ✓ | 是 |
| subscriber_name | TEXT |  | 否 |
| subscribe_events | TEXT |  | 是 |
| priority | INTEGER |  | 是 |
| handler_status | TEXT |  | 是 |
| last_heartbeat | TEXT |  | 是 |
| registered_at | TEXT |  | 是 |

### mt_collab_chain_execution (24 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| chain_id | TEXT | ✓ | 是 |
| event_type | TEXT |  | 否 |
| chain_name | TEXT |  | 是 |
| trigger_time | TEXT |  | 是 |
| step_count | INTEGER |  | 是 |
| success_count | INTEGER |  | 是 |
| fail_count | INTEGER |  | 是 |
| total_duration_ms | REAL |  | 是 |
| chain_result | TEXT |  | 是 |
| chain_status | TEXT |  | 是 |
| bottleneck | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_collab_channel (6,137 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| channel_id | INTEGER | ✓ | 是 |
| hall_task_id | INTEGER |  | 是 |
| title | TEXT |  | 否 |
| domain | TEXT |  | 是 |
| host_team | TEXT |  | 是 |
| status | TEXT |  | 是 |
| msg_count | INTEGER |  | 是 |
| silent_alert_at | TEXT |  | 是 |
| last_activity_at | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |
| flow_id | TEXT |  | 是 |

### mt_collab_growth (4 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| employee_id | TEXT |  | 否 |
| from_tier | TEXT |  | 是 |
| to_tier | TEXT |  | 是 |
| proposals_handled | INTEGER |  | 是 |
| teams_led | INTEGER |  | 是 |
| complex_problems_solved | INTEGER |  | 是 |
| growth_evidence | TEXT |  | 是 |
| growth_insight | TEXT |  | 是 |
| calibration_source | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_collab_hub_network (15 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| hub_id | TEXT | ✓ | 是 |
| galaxy | TEXT |  | 否 |
| hub_center | TEXT |  | 否 |
| member_centers | TEXT |  | 是 |
| last_broadcast | TEXT |  | 是 |
| coverage_pct | REAL |  | 是 |
| created_at | TEXT |  | 是 |

### mt_collab_message (69,739 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| msg_id | INTEGER | ✓ | 是 |
| channel_id | INTEGER |  | 否 |
| actor | TEXT |  | 否 |
| actor_type | TEXT |  | 否 |
| msg_type | TEXT |  | 否 |
| content | TEXT |  | 否 |
| ref_msg_id | INTEGER |  | 是 |
| broadcast_from | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |
| flow_id | TEXT |  | 是 |

### mt_collab_minutes (15 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| plan_id | INTEGER |  | 否 |
| proposal_id | INTEGER |  | 是 |
| title | TEXT |  | 是 |
| participants | TEXT |  | 是 |
| agenda | TEXT |  | 是 |
| decisions | TEXT |  | 是 |
| key_insights | TEXT |  | 是 |
| action_items | TEXT |  | 是 |
| risks_identified | TEXT |  | 是 |
| alternatives_considered | TEXT |  | 是 |
| minutes_markdown | TEXT |  | 是 |
| auto_generated | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_collab_pact (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| pact_id | TEXT | ✓ | 是 |
| center_a | TEXT |  | 否 |
| center_b | TEXT |  | 否 |
| pact_type | TEXT |  | 否 |
| obligations | TEXT |  | 是 |
| formed_by | TEXT |  | 是 |
| confidence | REAL |  | 是 |
| active | INTEGER |  | 是 |
| formed_at | TEXT |  | 是 |

### mt_collab_participation (49,754 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| channel_id | INTEGER |  | 否 |
| actor | TEXT |  | 否 |
| actor_type | TEXT |  | 否 |
| must_speak | INTEGER |  | 是 |
| spoke_count | INTEGER |  | 是 |
| last_spoke_at | TEXT |  | 是 |
| silent_flag | INTEGER |  | 是 |
| updated_at | TEXT |  | 是 |
| center_id | INTEGER |  | 是 |
| center_domain | TEXT |  | 是 |

### mt_collab_plan (25 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| proposal_id | INTEGER |  | 否 |
| plan_hash | TEXT |  | 是 |
| tier | TEXT |  | 是 |
| total_amount | REAL |  | 是 |
| risk_level | TEXT |  | 是 |
| complexity | REAL |  | 是 |
| urgency | REAL |  | 是 |
| recommended_roles | TEXT |  | 是 |
| role_weights | TEXT |  | 是 |
| lead_employee | TEXT |  | 是 |
| supporting_employees | TEXT |  | 是 |
| external_inputs | TEXT |  | 是 |
| plan_summary | TEXT |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_collab_role_stats (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| role_name | TEXT | ✓ | 是 |
| total_interventions | INTEGER |  | 是 |
| successful | INTEGER |  | 是 |
| impact_score | REAL |  | 是 |
| avg_weight | REAL |  | 是 |
| last_used | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_collab_trace (88 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| plan_id | INTEGER |  | 否 |
| proposal_id | INTEGER |  | 是 |
| step_order | INTEGER |  | 是 |
| trace_type | TEXT |  | 是 |
| actor_role | TEXT |  | 是 |
| actor_employee | TEXT |  | 是 |
| action | TEXT |  | 是 |
| input_snapshot | TEXT |  | 是 |
| output_snapshot | TEXT |  | 是 |
| decision_point | TEXT |  | 是 |
| adopted | TEXT |  | 是 |
| rejected | TEXT |  | 是 |
| reasoning | TEXT |  | 是 |
| weight_in_plan | REAL |  | 是 |
| trace_hash | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_community_calibration (82 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| employee_id | TEXT |  | 否 |
| calibration_type | TEXT |  | 是 |
| before_level | REAL |  | 是 |
| after_level | REAL |  | 是 |
| trigger_event | TEXT |  | 是 |
| calibration_logic | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_community_capability (93 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| role | TEXT |  | 否 |
| skill | TEXT |  | 否 |
| category | TEXT |  | 是 |
| required_level | REAL |  | 是 |
| weight | REAL |  | 是 |
| assessment_method | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_community_mentorship (21 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| mentor_id | TEXT |  | 否 |
| mentee_id | TEXT |  | 否 |
| skill_focus | TEXT |  | 是 |
| status | TEXT |  | 是 |
| start_date | TEXT |  | 是 |
| grad_date | TEXT |  | 是 |
| grad_score | REAL |  | 是 |
| lessons_count | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_community_permission (46 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| role | TEXT |  | 否 |
| action | TEXT |  | 否 |
| target | TEXT |  | 是 |
| min_level | REAL |  | 是 |
| requires_seal | INTEGER |  | 是 |
| requires_vote | INTEGER |  | 是 |
| risk_level | TEXT |  | 是 |
| enabled | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_community_review (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| employee_id | TEXT |  | 否 |
| review_type | TEXT |  | 是 |
| focus_skills | TEXT |  | 是 |
| key_insights | TEXT |  | 是 |
| action_items | TEXT |  | 是 |
| reviewed_by | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_community_skill_snapshot (63 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| employee_id | TEXT |  | 否 |
| skill | TEXT |  | 否 |
| current_level | REAL |  | 是 |
| last_demo | TEXT |  | 是 |
| verified_by | TEXT |  | 是 |
| verified_at | TEXT |  | 是 |
| trend | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_community_training (123 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| employee_id | TEXT |  | 否 |
| course_name | TEXT |  | 否 |
| course_type | TEXT |  | 是 |
| source | TEXT |  | 是 |
| status | TEXT |  | 是 |
| progress | REAL |  | 是 |
| score | REAL |  | 是 |
| reflections | TEXT |  | 是 |
| started_at | TEXT |  | 是 |
| completed_at | TEXT |  | 是 |

### mt_compliance_audit (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| proposal_id | INTEGER |  | 是 |
| proposal_no | TEXT |  | 是 |
| channel | TEXT |  | 是 |
| ptype | TEXT |  | 是 |
| amount | REAL |  | 是 |
| qty | REAL |  | 是 |
| price | REAL |  | 是 |
| stage | TEXT |  | 是 |
| ok | INTEGER |  | 是 |
| blocks | TEXT |  | 是 |
| warnings | TEXT |  | 是 |
| fees | TEXT |  | 是 |
| policy_snapshot | TEXT |  | 是 |
| operator | TEXT |  | 是 |
| data_scope | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_consensus (339 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| round | INTEGER | ✓ | 是 |
| block_height | INTEGER |  | 是 |
| proposer | TEXT |  | 是 |
| validators | TEXT |  | 是 |
| votes_for | INTEGER |  | 是 |
| votes_against | INTEGER |  | 是 |
| consensus_reached | INTEGER |  | 是 |
| reached_at | TEXT |  | 是 |

### mt_copy_permanent_archive (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| copy_id | INTEGER | ✓ | 是 |
| copy_category | TEXT |  | 是 |
| copy_source | TEXT |  | 是 |
| copy_content | TEXT |  | 是 |
| archive_status | TEXT |  | 是 |
| use_count | INTEGER |  | 是 |
| last_used_at | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_crypto_keys (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| key_id | TEXT | ✓ | 是 |
| key_type | TEXT |  | 否 |
| key_name | TEXT |  | 是 |
| key_b64 | TEXT |  | 否 |
| is_active | INTEGER |  | 是 |
| purpose | TEXT |  | 是 |
| expires_at | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_crypto_log (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| op_id | INTEGER | ✓ | 是 |
| operation | TEXT |  | 否 |
| key_id | TEXT |  | 是 |
| algorithm | TEXT |  | 是 |
| data_len | INTEGER |  | 是 |
| latency_ms | REAL |  | 是 |
| success | INTEGER |  | 是 |
| user_id | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_cve_watch (5 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| cve_id | TEXT | ✓ | 是 |
| title | TEXT |  | 是 |
| cvss | REAL |  | 是 |
| severity | TEXT |  | 是 |
| vendor | TEXT |  | 是 |
| product | TEXT |  | 是 |
| version_range | TEXT |  | 是 |
| our_stack_match | INTEGER |  | 是 |
| priority | TEXT |  | 是 |
| watch_status | TEXT |  | 是 |
| patch_available | INTEGER |  | 是 |
| patch_url | TEXT |  | 是 |
| reference_urls | TEXT |  | 是 |
| last_synced_at | TEXT |  | 是 |

### mt_daemon_registry (34 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| process_name | TEXT | ✓ | 是 |
| daemon_name | TEXT |  | 是 |
| duty | TEXT |  | 是 |
| daemon_duty | TEXT |  | 是 |
| description | TEXT |  | 是 |
| dependencies | TEXT |  | 是 |
| priority | TEXT |  | 是 |
| status | TEXT |  | 是 |
| pid | INTEGER |  | 是 |
| current_state | TEXT |  | 是 |
| inspect_cycle | TEXT |  | 是 |
| interval_sec | INTEGER |  | 是 |
| source | TEXT |  | 是 |
| restart_count | INTEGER |  | 是 |
| registered_at | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| last_heartbeat | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |
| last_error | TEXT |  | 是 |

### mt_data_anomalies (3,733 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| anomaly_type | TEXT |  | 是 |
| target | TEXT |  | 是 |
| metric | TEXT |  | 是 |
| expected | REAL |  | 是 |
| actual | REAL |  | 是 |
| severity | TEXT |  | 是 |
| details | TEXT |  | 是 |
| resolved | INTEGER |  | 是 |
| resolution | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| resolved_at | TEXT |  | 是 |

### mt_db_sync_log (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| log_id | INTEGER | ✓ | 是 |
| run_id | TEXT |  | 是 |
| synced_at | TEXT |  | 是 |
| table_name | TEXT |  | 是 |
| target_db | TEXT |  | 是 |
| inserted | INTEGER |  | 是 |
| updated | INTEGER |  | 是 |
| skipped | INTEGER |  | 是 |
| note | TEXT |  | 是 |

### mt_dead_letter_queue (21,908 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| dlq_id | TEXT | ✓ | 是 |
| event_type | TEXT |  | 否 |
| source | TEXT |  | 是 |
| payload | TEXT |  | 是 |
| original_handler | TEXT |  | 是 |
| error_msg | TEXT |  | 是 |
| retry_count | INTEGER |  | 是 |
| max_retries | INTEGER |  | 是 |
| first_failed | TEXT |  | 否 |
| last_failed | TEXT |  | 是 |
| resolution | TEXT |  | 是 |
| resolved_at | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_doc_registry (11 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| feature_key | TEXT |  | 是 |
| name | TEXT |  | 是 |
| file_path | TEXT |  | 是 |
| doc_line | TEXT |  | 是 |
| fingerprint | TEXT |  | 是 |
| last_synced_at | TEXT |  | 是 |

### mt_eigenflux_invite_log (18 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| invite_id | TEXT | ✓ | 是 |
| expert_name | TEXT |  | 是 |
| expert_role | TEXT |  | 是 |
| expert_domain | TEXT |  | 是 |
| invite_source | TEXT |  | 是 |
| invite_status | TEXT |  | 是 |
| invited_at | TEXT |  | 否 |

### mt_employee_chat (4 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| chat_id | TEXT | ✓ | 是 |
| employee_id | TEXT |  | 否 |
| message | TEXT |  | 否 |
| role | TEXT |  | 是 |
| context_json | TEXT |  | 是 |
| ai_model | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_eng_track_log (610 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| cycle_no | INTEGER |  | 是 |
| action | TEXT |  | 否 |
| track | TEXT |  | 是 |
| input_count | INTEGER |  | 是 |
| output_count | INTEGER |  | 是 |
| detail | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_eng_tracks (15 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| track | TEXT |  | 否 |
| family | TEXT |  | 否 |
| family_en | TEXT |  | 是 |
| min_diff | INTEGER |  | 是 |
| max_diff | INTEGER |  | 是 |
| description | TEXT |  | 是 |
| target_count | INTEGER |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_firewall_rules (16 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| rule_type | TEXT |  | 否 |
| rule_name | TEXT |  | 是 |
| pattern | TEXT |  | 是 |
| action | TEXT |  | 是 |
| priority | INTEGER |  | 是 |
| cve_id | TEXT |  | 是 |
| threat_signal_id | INTEGER |  | 是 |
| source | TEXT |  | 是 |
| active | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_fm_brain_feed (148,615 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| stream_name | TEXT |  | 是 |
| category | TEXT |  | 是 |
| asr_text | TEXT |  | 是 |
| trigger_keywords | TEXT |  | 是 |
| emotion | TEXT |  | 是 |
| emotion_score | REAL |  | 是 |
| has_price_info | INTEGER |  | 是 |
| has_policy | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_futuresight_scenario (18 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| scenario_id | TEXT | ✓ | 是 |
| scenario_name | TEXT |  | 否 |
| session_id | TEXT |  | 否 |
| total_return | REAL |  | 是 |
| max_drawdown | REAL |  | 是 |
| var_95 | REAL |  | 是 |
| sharpe | REAL |  | 是 |
| risk_score | REAL |  | 是 |
| recommendation | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_hall_flow_timeline (71,792 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| task_id | INTEGER |  | 否 |
| from_status | TEXT |  | 是 |
| to_status | TEXT |  | 是 |
| actor | TEXT |  | 是 |
| reason | TEXT |  | 是 |
| extra | TEXT |  | 是 |
| transition_at | TEXT |  | 是 |

### mt_i18n_catalog (5,408 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| catalog_id | TEXT | ✓ | 是 |
| source_string | TEXT |  | 否 |
| source_file | TEXT |  | 是 |
| zh_cn | TEXT |  | 是 |
| en_us | TEXT |  | 是 |
| ja_jp | TEXT |  | 是 |
| ko_kr | TEXT |  | 是 |
| status | TEXT |  | 是 |
| confidence | REAL |  | 是 |
| translated_at | TEXT |  | 是 |
| translator | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_i18n_keys (205 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| key_id | INTEGER | ✓ | 是 |
| key | TEXT |  | 否 |
| source | TEXT |  | 是 |
| domain | TEXT |  | 是 |
| zh_cn | TEXT |  | 否 |
| ja_jp | TEXT |  | 是 |
| en_us | TEXT |  | 是 |
| remark | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |
| zh_tw | TEXT |  | 是 |

### mt_i18n_progress (4 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| progress_id | TEXT | ✓ | 是 |
| language | TEXT |  | 否 |
| total_strings | INTEGER |  | 是 |
| translated | INTEGER |  | 是 |
| missing | INTEGER |  | 是 |
| auto_translated | INTEGER |  | 是 |
| manual_review | INTEGER |  | 是 |
| completion_pct | REAL |  | 是 |
| last_scan | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_intel_brain_feed (14,144 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| source | TEXT |  | 是 |
| source_type | TEXT |  | 是 |
| category | TEXT |  | 是 |
| content | TEXT |  | 是 |
| encrypted | INTEGER |  | 是 |
| enc_nonce | TEXT |  | 是 |
| trigger_keywords | TEXT |  | 是 |
| emotion | TEXT |  | 是 |
| emotion_score | REAL |  | 是 |
| has_price_info | INTEGER |  | 是 |
| has_policy | INTEGER |  | 是 |
| external_id | TEXT |  | 是 |
| pub_time | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_investment_proposal (779 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| proposal_type | TEXT |  | 是 |
| channel | TEXT |  | 是 |
| proposer | TEXT |  | 是 |
| amount | REAL |  | 是 |
| target_price | REAL |  | 是 |
| expected_return | REAL |  | 是 |
| rationale | TEXT |  | 是 |
| risk_assessment | TEXT |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |
| seal_code | TEXT |  | 是 |
| seal_token | TEXT |  | 是 |
| seal_requested_at | TEXT |  | 是 |
| seal_granted_at | TEXT |  | 是 |
| seal_verified_at | TEXT |  | 是 |
| seal_used_at | TEXT |  | 是 |
| seal_amount | TEXT |  | 是 |
| proposal_no | TEXT |  | 是 |

### mt_jimeng_prompts (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| prompt_id | TEXT | ✓ | 是 |
| scene_id | TEXT |  | 是 |
| prompt_enhanced | TEXT |  | 是 |
| negative_prompt | TEXT |  | 是 |
| duration_sec | INTEGER |  | 是 |
| aspect_ratio | TEXT |  | 是 |
| created_at | REAL |  | 是 |

### mt_jimeng_tasks (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| task_id | TEXT | ✓ | 是 |
| project_id | TEXT |  | 是 |
| prompt | TEXT |  | 是 |
| aspect_ratio | TEXT |  | 是 |
| duration_sec | INTEGER |  | 是 |
| status | TEXT |  | 是 |
| volc_task_id | TEXT |  | 是 |
| result_url | TEXT |  | 是 |
| local_path | TEXT |  | 是 |
| error_code | TEXT |  | 是 |
| error_message | TEXT |  | 是 |
| prompt_tokens | INTEGER |  | 是 |
| cost_cents | REAL |  | 是 |
| created_at | REAL |  | 是 |
| updated_at | REAL |  | 是 |
| completed_at | REAL |  | 是 |
| triggered_by | TEXT |  | 是 |

### mt_lab_assignments (13,148 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| suggestion_id | INTEGER |  | 否 |
| center_id | INTEGER |  | 否 |
| employee_names | TEXT |  | 是 |
| professor_names | TEXT |  | 是 |
| expert_verdict | TEXT |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| hall_task_id | INTEGER |  | 是 |

### mt_lab_audit_log (11,799 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| operator | TEXT |  | 否 |
| operator_role | TEXT |  | 是 |
| center | TEXT |  | 否 |
| action | TEXT |  | 否 |
| subject | TEXT |  | 是 |
| detail_json | TEXT |  | 是 |
| ip | TEXT |  | 是 |
| user_agent | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lab_chat (2 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| chat_id | TEXT | ✓ | 是 |
| exp_id | TEXT |  | 否 |
| part_id | TEXT |  | 是 |
| role | TEXT |  | 是 |
| message | TEXT |  | 否 |
| context_json | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lab_collab (11,935 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| hall_task_id | INTEGER |  | 否 |
| mode | TEXT |  | 否 |
| primary_center_id | INTEGER |  | 否 |
| collab_center_ids | TEXT |  | 是 |
| status | TEXT |  | 是 |
| handoff_seq | INTEGER |  | 是 |
| review_round | INTEGER |  | 是 |
| sla_hours | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_lab_deliberations (63,802 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| assignment_id | INTEGER |  | 否 |
| round_no | INTEGER |  | 是 |
| speaker | TEXT |  | 否 |
| role | TEXT |  | 否 |
| viewpoint | TEXT |  | 是 |
| vote | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lab_experiment (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| exp_id | TEXT | ✓ | 是 |
| title | TEXT |  | 否 |
| description | TEXT |  | 是 |
| type | TEXT |  | 是 |
| status | TEXT |  | 是 |
| initial_cash | REAL |  | 是 |
| start_date | TEXT |  | 是 |
| end_date | TEXT |  | 是 |
| market_condition | TEXT |  | 是 |
| created_by | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_lab_hr_log (26,733 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| employee_name | TEXT |  | 否 |
| employee_code | TEXT |  | 是 |
| role | TEXT |  | 是 |
| hall_task_id | INTEGER |  | 是 |
| action | TEXT |  | 是 |
| verdict | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lab_participant (36 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| part_id | TEXT | ✓ | 是 |
| exp_id | TEXT |  | 否 |
| name | TEXT |  | 否 |
| role | TEXT |  | 是 |
| is_ai | INTEGER |  | 是 |
| ai_employee_id | TEXT |  | 是 |
| current_cash | REAL |  | 是 |
| initial_cash | REAL |  | 是 |
| score | REAL |  | 是 |
| join_at | TEXT |  | 是 |

### mt_lab_portfolio (2 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| port_id | TEXT | ✓ | 是 |
| exp_id | TEXT |  | 否 |
| part_id | TEXT |  | 否 |
| symbol | TEXT |  | 否 |
| qty | INTEGER |  | 是 |
| avg_cost | REAL |  | 是 |

### mt_lab_report (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| report_id | TEXT | ✓ | 是 |
| exp_id | TEXT |  | 否 |
| report_type | TEXT |  | 是 |
| content | TEXT |  | 是 |
| lessons_json | TEXT |  | 是 |
| brain_feed_ids | TEXT |  | 是 |
| created_by | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lab_suggestions (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| kind | TEXT |  | 否 |
| subject | TEXT |  | 否 |
| reason | TEXT |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lab_task_events (4,527 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| hall_task_id | INTEGER |  | 否 |
| event | TEXT |  | 否 |
| actor | TEXT |  | 是 |
| actor_role | TEXT |  | 是 |
| note | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lab_task_hall (19,294 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| title | TEXT |  | 否 |
| description | TEXT |  | 是 |
| source | TEXT |  | 是 |
| source_id | INTEGER |  | 是 |
| priority | TEXT |  | 是 |
| status | TEXT |  | 是 |
| center_id | INTEGER |  | 是 |
| assignment_id | INTEGER |  | 是 |
| verdict | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| dispatched_at | TEXT |  | 是 |
| claim_owner | TEXT |  | 是 |
| claim_owner_role | TEXT |  | 是 |
| claim_type | TEXT |  | 是 |
| claimed_at | TEXT |  | 是 |
| started_at | TEXT |  | 是 |
| progress | TEXT |  | 是 |
| progress_note | TEXT |  | 是 |
| delivered_at | TEXT |  | 是 |

### mt_lab_trade (2 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| trade_id | TEXT | ✓ | 是 |
| exp_id | TEXT |  | 否 |
| part_id | TEXT |  | 否 |
| symbol | TEXT |  | 否 |
| stock_name | TEXT |  | 是 |
| action | TEXT |  | 是 |
| qty | INTEGER |  | 是 |
| price | REAL |  | 是 |
| reason | TEXT |  | 是 |
| ollama_feedback | TEXT |  | 是 |
| feedback_score | REAL |  | 是 |
| market_price | REAL |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lab_workflows (18 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| name | TEXT |  | 否 |
| domain | TEXT |  | 是 |
| direction | TEXT |  | 否 |
| description | TEXT |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lang_activity_log (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| username | TEXT |  | 否 |
| action | TEXT |  | 否 |
| detail | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lang_courses (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| course_code | TEXT |  | 否 |
| language | TEXT |  | 否 |
| cefr | TEXT |  | 否 |
| native_level | TEXT |  | 是 |
| title | TEXT |  | 否 |
| description | TEXT |  | 是 |
| difficulty | INTEGER |  | 是 |
| lesson_count | INTEGER |  | 是 |
| order_no | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lang_difficulty_events (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| username | TEXT |  | 否 |
| language | TEXT |  | 否 |
| old_band | TEXT |  | 是 |
| new_band | TEXT |  | 是 |
| trigger | TEXT |  | 是 |
| correct_rate | REAL |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lang_grammar (91 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| employee_id | TEXT |  | 是 |
| grammar_point | TEXT |  | 否 |
| lang | TEXT |  | 是 |
| practice_text | TEXT |  | 是 |
| correct_answer | TEXT |  | 是 |
| user_answer | TEXT |  | 是 |
| result | INTEGER |  | 是 |
| hint | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lang_learner_profiles (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| username | TEXT |  | 否 |
| language | TEXT |  | 否 |
| level | TEXT |  | 是 |
| mastery | TEXT |  | 是 |
| correct_rate | REAL |  | 是 |
| recent_trend | REAL |  | 是 |
| difficulty_band | TEXT |  | 是 |
| style | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_lang_lessons (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| lesson_code | TEXT |  | 否 |
| course_code | TEXT |  | 否 |
| title | TEXT |  | 否 |
| lesson_type | TEXT |  | 否 |
| content | TEXT |  | 是 |
| difficulty | INTEGER |  | 是 |
| order_no | INTEGER |  | 是 |

### mt_lang_listening (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| audio_id | TEXT |  | 否 |
| language | TEXT |  | 否 |
| title | TEXT |  | 否 |
| transcript | TEXT |  | 否 |
| translation | TEXT |  | 是 |
| questions | TEXT |  | 是 |
| cefr | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lang_paths (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| username | TEXT |  | 否 |
| language | TEXT |  | 否 |
| level | TEXT |  | 是 |
| plan | TEXT |  | 是 |
| generated_at | TEXT |  | 是 |

### mt_lang_post_comments (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| post_id | TEXT |  | 否 |
| username | TEXT |  | 否 |
| content | TEXT |  | 否 |
| created_at | TEXT |  | 是 |

### mt_lang_posts (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| post_id | TEXT |  | 否 |
| username | TEXT |  | 否 |
| language | TEXT |  | 是 |
| title | TEXT |  | 否 |
| content | TEXT |  | 否 |
| likes | INTEGER |  | 是 |
| comment_count | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lang_practice_results (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| username | TEXT |  | 否 |
| language | TEXT |  | 否 |
| paper_code | TEXT |  | 是 |
| score | REAL |  | 是 |
| max_score | REAL |  | 是 |
| item_results | TEXT |  | 是 |
| error_attribution | TEXT |  | 是 |
| weak_points | TEXT |  | 是 |
| graded_by | TEXT |  | 是 |
| graded_at | TEXT |  | 是 |

### mt_lang_progress (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| username | TEXT |  | 否 |
| language | TEXT |  | 否 |
| lesson_code | TEXT |  | 是 |
| action | TEXT |  | 是 |
| score | REAL |  | 是 |
| detail | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lang_qbank (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| qcode | TEXT |  | 否 |
| language | TEXT |  | 否 |
| question | TEXT |  | 否 |
| q_type | TEXT |  | 是 |
| topic | TEXT |  | 是 |
| knowledge_points | TEXT |  | 是 |
| difficulty | INTEGER |  | 是 |
| answer | TEXT |  | 是 |
| solution | TEXT |  | 是 |
| analysis | TEXT |  | 是 |
| hints | TEXT |  | 是 |
| source | TEXT |  | 是 |
| expert_id | TEXT |  | 是 |
| model_ref | TEXT |  | 是 |
| quality_score | REAL |  | 是 |
| usage_count | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_lang_session (27 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| session_id | TEXT | ✓ | 是 |
| employee_id | TEXT |  | 是 |
| lang | TEXT |  | 是 |
| session_type | TEXT |  | 是 |
| started_at | TEXT |  | 是 |
| ended_at | TEXT |  | 是 |
| duration_ms | REAL |  | 是 |
| score | REAL |  | 是 |
| items_count | INTEGER |  | 是 |
| correct_count | INTEGER |  | 是 |

### mt_lang_speaking (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| sp_id | TEXT |  | 否 |
| language | TEXT |  | 否 |
| sentence | TEXT |  | 否 |
| translation | TEXT |  | 是 |
| tips | TEXT |  | 是 |
| cefr | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lang_user_achievements (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| username | TEXT |  | 否 |
| ach_code | TEXT |  | 否 |
| earned_at | TEXT |  | 是 |

### mt_lang_users (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| username | TEXT |  | 否 |
| password_hash | TEXT |  | 否 |
| display_name | TEXT |  | 是 |
| token | TEXT |  | 是 |
| target_languages | TEXT |  | 是 |
| xp | INTEGER |  | 是 |
| level | INTEGER |  | 是 |
| streak_days | INTEGER |  | 是 |
| last_active_date | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_lang_vocab (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| word_id | TEXT |  | 否 |
| language | TEXT |  | 否 |
| word | TEXT |  | 否 |
| reading | TEXT |  | 是 |
| meaning | TEXT |  | 否 |
| example_sentence | TEXT |  | 是 |
| example_translation | TEXT |  | 是 |
| cefr | TEXT |  | 是 |
| topic | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lang_vocab_review (60 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| session_id | TEXT |  | 是 |
| word | TEXT |  | 否 |
| reading | TEXT |  | 是 |
| meaning | TEXT |  | 是 |
| review_result | TEXT |  | 是 |
| review_interval | INTEGER |  | 是 |
| next_review | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_lang_vocab_reviews (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| username | TEXT |  | 否 |
| word_id | TEXT |  | 否 |
| ease | REAL |  | 是 |
| interval_days | INTEGER |  | 是 |
| due_date | TEXT |  | 否 |
| repetitions | INTEGER |  | 是 |
| last_result | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_live_account (191 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| total_assets | REAL |  | 是 |
| available | REAL |  | 是 |
| market_value | REAL |  | 是 |
| cash | REAL |  | 是 |
| pnl | REAL |  | 是 |
| server_time | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |
| initial_cash | REAL |  | 是 |

### mt_live_bank_product (3 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| product_code | TEXT |  | 是 |
| product_name | TEXT |  | 是 |
| bank | TEXT |  | 是 |
| amount | REAL |  | 是 |
| expected_return | REAL |  | 是 |
| term_type | TEXT |  | 是 |
| status | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_live_business_inv (3 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| inv_code | TEXT |  | 是 |
| inv_name | TEXT |  | 是 |
| inv_type | TEXT |  | 是 |
| amount | REAL |  | 是 |
| equity_pct | REAL |  | 是 |
| expected_irr | REAL |  | 是 |
| status | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_live_fund_position (4 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| fund_code | TEXT |  | 是 |
| fund_name | TEXT |  | 是 |
| price | REAL |  | 是 |
| qty | REAL |  | 是 |
| pnl | REAL |  | 是 |
| today_pnl | REAL |  | 是 |
| prev_close | REAL |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_live_insurance (3 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| policy_code | TEXT |  | 是 |
| policy_name | TEXT |  | 是 |
| insurer | TEXT |  | 是 |
| premium | REAL |  | 是 |
| coverage | REAL |  | 是 |
| policy_type | TEXT |  | 是 |
| status | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_live_metal_position (3 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| metal_name | TEXT |  | 是 |
| metal_type | TEXT |  | 是 |
| price | REAL |  | 是 |
| qty | REAL |  | 是 |
| pnl | REAL |  | 是 |
| today_pnl | REAL |  | 是 |
| prev_close | REAL |  | 是 |
| unit | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_live_order (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| order_id | TEXT |  | 是 |
| symbol | TEXT |  | 否 |
| side | TEXT |  | 是 |
| qty | REAL |  | 是 |
| price | REAL |  | 是 |
| mode | TEXT |  | 是 |
| verdict | TEXT |  | 是 |
| reason | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_live_position (7 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| symbol | TEXT |  | 否 |
| name | TEXT |  | 是 |
| qty | REAL |  | 是 |
| avg_cost | REAL |  | 是 |
| price | REAL |  | 是 |
| pnl | REAL |  | 是 |
| pnl_pct | REAL |  | 是 |
| updated_at | TEXT |  | 是 |
| prev_close | REAL |  | 是 |
| today_pnl | REAL |  | 是 |

### mt_live_term_deposit (3 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| deposit_code | TEXT |  | 是 |
| bank | TEXT |  | 是 |
| amount | REAL |  | 是 |
| rate | REAL |  | 是 |
| term_months | INTEGER |  | 是 |
| maturity_date | TEXT |  | 是 |
| status | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_live_trade_log (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| symbol | TEXT |  | 否 |
| side | TEXT |  | 是 |
| qty | REAL |  | 是 |
| price | REAL |  | 是 |
| amount | REAL |  | 是 |
| fee | REAL |  | 是 |
| mode | TEXT |  | 是 |
| order_id | TEXT |  | 是 |
| status | TEXT |  | 是 |
| reason | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_machine_status (3 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| machine_id | TEXT | ✓ | 是 |
| machine_name | TEXT |  | 否 |
| machine_role | TEXT |  | 是 |
| hostname | TEXT |  | 是 |
| ssh_available | INTEGER |  | 是 |
| last_ping_ms | REAL |  | 是 |
| last_sync_success | TEXT |  | 是 |
| db_checksum | TEXT |  | 是 |
| code_checksum | TEXT |  | 是 |
| uptime_seconds | REAL |  | 是 |
| active_daemons | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_market_radar_cache (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| symbol | TEXT | ✓ | 是 |
| name | TEXT |  | 是 |
| price | REAL |  | 是 |
| change_pct | REAL |  | 是 |
| volume | REAL |  | 是 |
| turnover | REAL |  | 是 |
| anomaly_type | TEXT |  | 是 |
| anomaly_score | REAL |  | 是 |
| tick_count | INTEGER |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_math_difficulty_events (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| student | TEXT |  | 否 |
| old_band | TEXT |  | 是 |
| new_band | TEXT |  | 是 |
| trigger | TEXT |  | 是 |
| correct_rate | REAL |  | 是 |
| created_at | TEXT |  | 是 |

### mt_math_gradings (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| paper_id | INTEGER |  | 否 |
| student | TEXT |  | 否 |
| score | REAL |  | 否 |
| max_score | REAL |  | 否 |
| item_results | TEXT |  | 是 |
| error_attribution | TEXT |  | 是 |
| weak_points | TEXT |  | 是 |
| graded_by | TEXT |  | 是 |
| graded_at | TEXT |  | 是 |

### mt_math_learner_profiles (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| student | TEXT |  | 否 |
| stage | TEXT |  | 是 |
| level | TEXT |  | 是 |
| mastery | TEXT |  | 是 |
| correct_rate | REAL |  | 是 |
| recent_trend | REAL |  | 是 |
| difficulty_band | TEXT |  | 是 |
| style | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_math_papers (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| paper_code | TEXT |  | 否 |
| title | TEXT |  | 否 |
| paper_type | TEXT |  | 是 |
| stage | TEXT |  | 是 |
| difficulty_target | REAL |  | 是 |
| difficulty_actual | REAL |  | 是 |
| question_codes | TEXT |  | 是 |
| topic_coverage | TEXT |  | 是 |
| total_score | INTEGER |  | 是 |
| duration_min | INTEGER |  | 是 |
| status | TEXT |  | 是 |
| created_by | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_math_qbank (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| qcode | TEXT |  | 否 |
| stage | TEXT |  | 是 |
| subject | TEXT |  | 是 |
| question | TEXT |  | 否 |
| q_type | TEXT |  | 是 |
| topic | TEXT |  | 是 |
| knowledge_points | TEXT |  | 是 |
| difficulty | INTEGER |  | 是 |
| answer | TEXT |  | 是 |
| solution | TEXT |  | 是 |
| analysis | TEXT |  | 是 |
| hints | TEXT |  | 是 |
| source | TEXT |  | 是 |
| expert_id | TEXT |  | 是 |
| model_ref | TEXT |  | 是 |
| quality_score | REAL |  | 是 |
| usage_count | INTEGER |  | 是 |
| correct_rate | REAL |  | 是 |
| created_at | TEXT |  | 是 |

### mt_meeting_log (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| meeting_id | TEXT |  | 是 |
| title | TEXT |  | 是 |
| meeting_type | TEXT |  | 是 |
| convener | TEXT |  | 是 |
| recorder | TEXT |  | 是 |
| status | TEXT |  | 是 |
| agenda | TEXT |  | 是 |
| minutes | TEXT |  | 是 |
| archive_path | TEXT |  | 是 |
| recorded_at | TEXT |  | 是 |

### mt_neuron (285,869 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| neuron_id | INTEGER | ✓ | 是 |
| neuron_type | TEXT |  | 否 |
| ref_id | INTEGER |  | 是 |
| name | TEXT |  | 是 |
| domain | TEXT |  | 是 |
| weight | REAL |  | 是 |
| connected_to | TEXT |  | 是 |
| fire_count | INTEGER |  | 是 |
| last_fired_at | TEXT |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_node_access_pending (10 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| username | TEXT |  | 是 |
| node | TEXT |  | 是 |
| reason | TEXT |  | 是 |
| requested_at | TEXT |  | 是 |
| status | TEXT |  | 是 |
| reviewer | TEXT |  | 是 |
| reviewed_at | TEXT |  | 是 |
| decision | TEXT |  | 是 |

### mt_parliament_session (21 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| proposal_id | INTEGER |  | 否 |
| tier | TEXT |  | 是 |
| quorum_count | INTEGER |  | 是 |
| yes_weight | REAL |  | 是 |
| no_weight | REAL |  | 是 |
| veto_count | INTEGER |  | 是 |
| abstain_count | INTEGER |  | 是 |
| absent_count | INTEGER |  | 是 |
| threshold | REAL |  | 是 |
| final_score | REAL |  | 是 |
| result | TEXT |  | 是 |
| veto_triggered | INTEGER |  | 是 |
| started_at | TEXT |  | 是 |
| finished_at | TEXT |  | 是 |
| duration_ms | INTEGER |  | 是 |
| data_scope | TEXT |  | 是 |

### mt_parliament_vote_log (153 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| proposal_id | INTEGER |  | 否 |
| member_code | TEXT |  | 否 |
| member_name | TEXT |  | 是 |
| layer | TEXT |  | 是 |
| weight | REAL |  | 是 |
| vote | TEXT |  | 否 |
| score | REAL |  | 是 |
| reason | TEXT |  | 是 |
| veto_flag | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |
| data_scope | TEXT |  | 是 |

### mt_pollution_log (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| detected_at | TEXT |  | 否 |
| source_table | TEXT |  | 否 |
| source_session_id | TEXT |  | 是 |
| actual_prefix | TEXT |  | 是 |
| expected_prefixes | TEXT |  | 是 |
| severity | TEXT |  | 是 |
| details | TEXT |  | 是 |
| resolved | INTEGER |  | 是 |
| resolved_at | TEXT |  | 是 |

### mt_pollution_quarantine (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| quarantined_at | TEXT |  | 否 |
| source_table | TEXT |  | 否 |
| original_rowid | INTEGER |  | 是 |
| row_data | TEXT |  | 否 |
| reason | TEXT |  | 是 |
| hash | TEXT |  | 是 |

### mt_portfolio_target (8 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| channel_code | TEXT |  | 是 |
| channel_name | TEXT |  | 是 |
| target_pct | REAL |  | 是 |
| min_pct | REAL |  | 是 |
| max_pct | REAL |  | 是 |
| current_pct | REAL |  | 是 |
| last_rebalanced | TEXT |  | 是 |
| status | TEXT |  | 是 |

### mt_proposal_chain (24 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| chain_id | INTEGER | ✓ | 是 |
| chain_key | TEXT |  | 是 |
| chain_type | TEXT |  | 是 |
| summary | TEXT |  | 是 |
| seed_text | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_proposal_chain_members (418 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| chain_id | INTEGER |  | 否 |
| task_id | INTEGER |  | 否 |
| relation | TEXT |  | 是 |

### mt_proposal_followup (3,684 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| fu_id | INTEGER | ✓ | 是 |
| task_id | INTEGER |  | 否 |
| hall_code | TEXT |  | 是 |
| followup_at | TEXT |  | 否 |
| check_type | TEXT |  | 是 |
| status | TEXT |  | 是 |
| outcome | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_proposal_inquiry (105,568 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| inquiry_id | INTEGER | ✓ | 是 |
| hall_task_id | INTEGER |  | 否 |
| dimension_key | TEXT |  | 否 |
| dimension_label | TEXT |  | 否 |
| question_text | TEXT |  | 否 |
| auto_analysis_text | TEXT |  | 是 |
| suggested_answer | TEXT |  | 是 |
| user_answer | TEXT |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| flow_id | TEXT |  | 是 |

### mt_proposal_intel (13,945 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| task_id | INTEGER | ✓ | 是 |
| hall_code | TEXT |  | 是 |
| auto_tags | TEXT |  | 是 |
| intent_summary | TEXT |  | 是 |
| real_need | TEXT |  | 是 |
| benefit_estimate | TEXT |  | 是 |
| solution_path | TEXT |  | 是 |
| quality_score | INTEGER |  | 是 |
| quality_flags | TEXT |  | 是 |
| chain_id | INTEGER |  | 是 |
| parallel_id | INTEGER |  | 是 |
| auto_closed | INTEGER |  | 是 |
| closed_at | TEXT |  | 是 |
| escape_reason | TEXT |  | 是 |
| followup_state | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_proposal_tag_bank (31 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| tag | TEXT | ✓ | 是 |
| center_codes | TEXT |  | 是 |
| domain_hint | TEXT |  | 是 |
| hit_count | INTEGER |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_qbank_knowledge_point (45 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| kp_id | TEXT | ✓ | 是 |
| subject_id | TEXT |  | 是 |
| kp_name | TEXT |  | 否 |
| description | TEXT |  | 是 |
| parent_id | TEXT |  | 是 |
| difficulty | TEXT |  | 是 |
| question_count | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_qbank_questions (68 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| question_id | TEXT | ✓ | 是 |
| subject_id | TEXT |  | 是 |
| kp_id | TEXT |  | 是 |
| question_type | TEXT |  | 是 |
| difficulty | TEXT |  | 是 |
| question_text | TEXT |  | 否 |
| options_json | TEXT |  | 是 |
| correct_answer | TEXT |  | 是 |
| explanation | TEXT |  | 是 |
| tags_json | TEXT |  | 是 |
| confidence | REAL |  | 是 |
| usage_count | INTEGER |  | 是 |
| source | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_qbank_subject (8 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| subject_id | TEXT | ✓ | 是 |
| subject_name | TEXT |  | 否 |
| category | TEXT |  | 是 |
| difficulty | TEXT |  | 是 |
| question_count | INTEGER |  | 是 |
| description | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_roundtable_sessions (382 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| session_id | TEXT | ✓ | 是 |
| host_node | TEXT |  | 是 |
| guest_node | TEXT |  | 是 |
| agenda | TEXT |  | 是 |
| summary | TEXT |  | 是 |
| verdicts | TEXT |  | 是 |
| action_items | TEXT |  | 是 |
| brain_feed_ref | TEXT |  | 是 |
| source_task_ids | TEXT |  | 是 |
| status | TEXT |  | 是 |
| session_at | TEXT |  | 是 |
| closed_at | TEXT |  | 是 |

### mt_sa_dual_key_status (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| check_time | TEXT |  | 是 |
| vikey_present | INTEGER |  | 是 |
| vikey_verified | INTEGER |  | 是 |
| fingerprint_hash | TEXT |  | 是 |
| fingerprint_len | INTEGER |  | 是 |
| dual_authenticated | INTEGER |  | 是 |
| sa_layout | TEXT |  | 是 |
| trigger_reason | TEXT |  | 是 |
| note | TEXT |  | 是 |
| szu100_present | INTEGER |  | 是 |
| szu100_authentic | INTEGER |  | 是 |

### mt_safety_audit (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| ts | TEXT |  | 否 |
| action | TEXT |  | 否 |
| actor | TEXT |  | 是 |
| target | TEXT |  | 是 |
| details | TEXT |  | 是 |

### mt_screen_events (126 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| screen_name | TEXT |  | 是 |
| event_type | TEXT |  | 是 |
| content | TEXT |  | 是 |
| symbol | TEXT |  | 是 |
| value | REAL |  | 是 |
| prev_value | REAL |  | 是 |
| severity | TEXT |  | 是 |
| snapshot_path | TEXT |  | 是 |
| trigger_action | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_seal_audit (64 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| audit_id | INTEGER | ✓ | 是 |
| token_hash | TEXT |  | 是 |
| seal_code | TEXT |  | 是 |
| proposal_id | INTEGER |  | 是 |
| channel | TEXT |  | 是 |
| action | TEXT |  | 是 |
| operator | TEXT |  | 是 |
| amount | REAL |  | 是 |
| result | TEXT |  | 是 |
| reason | TEXT |  | 是 |
| related_trade_id | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |
| data_scope | TEXT |  | 是 |
| id | INTEGER |  | 是 |

### mt_seal_grant (40 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| grant_id | INTEGER | ✓ | 是 |
| seal_code | TEXT |  | 否 |
| grantee | TEXT |  | 否 |
| proposal_id | INTEGER |  | 是 |
| channel | TEXT |  | 是 |
| amount | REAL |  | 是 |
| used | REAL |  | 是 |
| remaining | REAL |  | 是 |
| expires_at | TEXT |  | 是 |
| status | TEXT |  | 是 |
| granted_at | TEXT |  | 是 |
| remark | TEXT |  | 是 |
| data_scope | TEXT |  | 是 |
| id | INTEGER |  | 是 |
| grant_status | TEXT |  | 是 |
| grant_reason | TEXT |  | 是 |

### mt_seal_registry (4 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| seal_code | TEXT | ✓ | 是 |
| seal_name | TEXT |  | 是 |
| seal_type | TEXT |  | 是 |
| max_per_tx | REAL |  | 是 |
| max_daily | REAL |  | 是 |
| requires_vote | INTEGER |  | 是 |
| description | TEXT |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| data_scope | TEXT |  | 是 |

### mt_seal_token (40 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| token_id | INTEGER | ✓ | 是 |
| seal_code | TEXT |  | 否 |
| token_hash | TEXT |  | 否 |
| grant_id | INTEGER |  | 是 |
| proposal_id | INTEGER |  | 是 |
| channel | TEXT |  | 是 |
| amount | REAL |  | 是 |
| status | TEXT |  | 是 |
| issued_at | TEXT |  | 是 |
| expires_at | TEXT |  | 是 |
| used_at | TEXT |  | 是 |
| revoked_at | TEXT |  | 是 |
| audit_ref | TEXT |  | 是 |
| data_scope | TEXT |  | 是 |
| id | INTEGER |  | 是 |

### mt_security_actions (837 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| action_type | TEXT |  | 否 |
| target | TEXT |  | 是 |
| actor | TEXT |  | 是 |
| detail | TEXT |  | 是 |
| result | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_signature_db (5 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| sig_hash | TEXT |  | 是 |
| sig_type | TEXT |  | 是 |
| sig_data | TEXT |  | 是 |
| source | TEXT |  | 是 |
| threat_level | TEXT |  | 是 |
| feed_count | INTEGER |  | 是 |
| fed_to_brain | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_skill_registry (245 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| skill_id | TEXT | ✓ | 是 |
| skill_name | TEXT |  | 是 |
| category | TEXT |  | 是 |
| trigger_keywords | TEXT |  | 是 |
| description | TEXT |  | 是 |
| source_daemon | TEXT |  | 是 |
| source_blueprint | TEXT |  | 是 |
| run_function | TEXT |  | 是 |
| input_schema | TEXT |  | 是 |
| output_schema | TEXT |  | 是 |
| priority | TEXT |  | 是 |
| readiness | INTEGER |  | 是 |
| usage_count | INTEGER |  | 是 |
| last_used | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |
| seed_template | TEXT |  | 是 |

### mt_skill_usage_log (500 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| log_id | INTEGER | ✓ | 是 |
| skill_id | TEXT |  | 否 |
| user_id | TEXT |  | 是 |
| employee_id | TEXT |  | 是 |
| context | TEXT |  | 是 |
| success | INTEGER |  | 是 |
| duration_ms | REAL |  | 是 |
| created_at | TEXT |  | 是 |

### mt_strategy_research (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| research_id | TEXT |  | 是 |
| title | TEXT |  | 是 |
| category | TEXT |  | 是 |
| severity | TEXT |  | 是 |
| event_id | TEXT |  | 是 |
| root_causes | TEXT |  | 是 |
| lessons_learned | TEXT |  | 是 |
| mitigations | TEXT |  | 是 |
| risk_level | TEXT |  | 是 |
| status | TEXT |  | 是 |
| flow_id | TEXT |  | 是 |
| published_at | TEXT |  | 是 |
| reported_to_committee | INTEGER |  | 是 |
| brain_fed | INTEGER |  | 是 |

### mt_strategy_risk_map (10 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| risk_code | TEXT |  | 是 |
| risk_name | TEXT |  | 是 |
| category | TEXT |  | 是 |
| current_level | TEXT |  | 是 |
| trigger_threshold | TEXT |  | 是 |
| mitigation_strategy | TEXT |  | 是 |
| owner_center | TEXT |  | 是 |
| last_updated | TEXT |  | 是 |
| status | TEXT |  | 是 |

### mt_switch_panel (13 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| switch_id | TEXT | ✓ | 是 |
| switch_name | TEXT |  | 否 |
| switch_value | TEXT |  | 否 |
| switch_type | TEXT |  | 是 |
| category | TEXT |  | 是 |
| description | TEXT |  | 是 |
| updated_by | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_sync_log (786 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| sync_id | TEXT | ✓ | 是 |
| sync_type | TEXT |  | 否 |
| direction | TEXT |  | 是 |
| target | TEXT |  | 是 |
| item | TEXT |  | 是 |
| bytes_transferred | INTEGER |  | 是 |
| files_changed | INTEGER |  | 是 |
| conflicts | INTEGER |  | 是 |
| duration_ms | REAL |  | 是 |
| status | TEXT |  | 是 |
| error_msg | TEXT |  | 是 |
| backup_path | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_sync_triggers (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| trigger_id | TEXT | ✓ | 是 |
| trigger_event | TEXT |  | 否 |
| sync_type | TEXT |  | 否 |
| source | TEXT |  | 是 |
| affected_tables | TEXT |  | 是 |
| success | INTEGER |  | 是 |
| duration_ms | INTEGER |  | 是 |
| error_msg | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_task_archive (7,801 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| task_id | INTEGER |  | 否 |
| hall_code | TEXT |  | 是 |
| case_no | TEXT |  | 是 |
| status_at_archive | TEXT |  | 是 |
| derived_backup_task | INTEGER |  | 是 |
| derived_research_task | INTEGER |  | 是 |
| supervision_owner | TEXT |  | 是 |
| summary | TEXT |  | 是 |
| detail_json | TEXT |  | 是 |
| archived_at | TEXT |  | 是 |

### mt_task_hall (6 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| hall_id | INTEGER | ✓ | 是 |
| hall_code | TEXT |  | 否 |
| task_title | TEXT |  | 否 |
| task_type | TEXT |  | 否 |
| description | TEXT |  | 是 |
| source | TEXT |  | 是 |
| source_id | TEXT |  | 是 |
| target_center | TEXT |  | 是 |
| hall_priority | TEXT |  | 是 |
| publish_at | TEXT |  | 是 |
| status | TEXT |  | 是 |
| deliverable | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| priority | INTEGER |  | 是 |
| notes | TEXT |  | 是 |
| claimant | TEXT |  | 是 |
| brain_feed_id | TEXT |  | 是 |
| claimed_at | TEXT |  | 是 |
| done_at | TEXT |  | 是 |

### mt_task_landing_log (10,688 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| task_id | INTEGER |  | 否 |
| hall_code | TEXT |  | 是 |
| landing_type | TEXT |  | 是 |
| result | TEXT |  | 是 |
| detail_json | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_task_queue (773 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| task_type | TEXT |  | 是 |
| from_center | TEXT |  | 是 |
| to_center | TEXT |  | 是 |
| status | TEXT |  | 是 |
| payload | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |
| priority | REAL |  | 是 |
| task_id | REAL |  | 是 |
| completed_at | REAL |  | 是 |
| duration_ms | REAL |  | 是 |

### mt_theme_registry (36 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| theme_id | TEXT | ✓ | 是 |
| center_name | TEXT |  | 否 |
| theme_name | TEXT |  | 否 |
| css_files | TEXT |  | 是 |
| body_class | TEXT |  | 是 |
| primary_color | TEXT |  | 是 |
| bg_color | TEXT |  | 是 |
| accent_color | TEXT |  | 是 |
| tokens_hash | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_threat_signals (5 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| source | TEXT |  | 否 |
| external_id | TEXT |  | 是 |
| title | TEXT |  | 是 |
| description | TEXT |  | 是 |
| cvss | REAL |  | 是 |
| severity | TEXT |  | 是 |
| affected_stack | TEXT |  | 是 |
| exploit_available | INTEGER |  | 是 |
| matches_our_stack | INTEGER |  | 是 |
| match_reason | TEXT |  | 是 |
| status | TEXT |  | 是 |
| raw_json | TEXT |  | 是 |
| published_at | TEXT |  | 是 |
| discovered_at | TEXT |  | 是 |

### mt_throttle_metrics (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| metric_id | TEXT | ✓ | 是 |
| event_type | TEXT |  | 否 |
| window_start | TEXT |  | 否 |
| request_count | INTEGER |  | 是 |
| throttled_count | INTEGER |  | 是 |
| avg_qps | REAL |  | 是 |
| max_qps | REAL |  | 是 |

### mt_time_sync_log (3 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| sync_id | TEXT | ✓ | 是 |
| check_time | TEXT |  | 是 |
| ntp_offset_ms | REAL |  | 是 |
| ntp_stratum | INTEGER |  | 是 |
| timezone_consistent | REAL |  | 是 |
| drift_tables | TEXT |  | 是 |
| anomaly_count | INTEGER |  | 是 |
| cron_ok | INTEGER |  | 是 |
| launchd_ok | INTEGER |  | 是 |
| is_trading_day | INTEGER |  | 是 |
| trading_session | TEXT |  | 是 |
| anchor_market_open | TEXT |  | 是 |
| anchor_market_close | TEXT |  | 是 |
| fix_sql_generated | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_token_wallets (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| user_id | TEXT |  | 是 |
| username | TEXT |  | 是 |
| is_guest | INTEGER |  | 是 |
| guest_device_hash | TEXT |  | 是 |
| balance | INTEGER |  | 是 |
| frozen | INTEGER |  | 是 |
| guest_free_grant | INTEGER |  | 是 |
| guest_consumed | INTEGER |  | 是 |
| expires_at | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_trade_log (63 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| trade_id | INTEGER |  | 是 |
| action | TEXT |  | 是 |
| symbol | TEXT |  | 是 |
| name | TEXT |  | 是 |
| qty | INTEGER |  | 是 |
| price | REAL |  | 是 |
| fill_price | REAL |  | 是 |
| fill_qty | INTEGER |  | 是 |
| fill_amount | REAL |  | 是 |
| amount | REAL |  | 是 |
| fee_total | REAL |  | 是 |
| reason | TEXT |  | 是 |
| trade_mode | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_trigger_execution_log (30,343 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| exec_id | TEXT | ✓ | 是 |
| event_id | TEXT |  | 是 |
| event_type | TEXT |  | 否 |
| handler_key | TEXT |  | 否 |
| target_engine | TEXT |  | 是 |
| started_at | TEXT |  | 否 |
| ended_at | TEXT |  | 是 |
| duration_ms | REAL |  | 是 |
| result | TEXT |  | 是 |
| error_msg | TEXT |  | 是 |
| retry_count | INTEGER |  | 是 |

### mt_trigger_gate (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| gate_id | TEXT | ✓ | 是 |
| gate_name | TEXT |  | 否 |
| gate_type | TEXT |  | 否 |
| condition_events | TEXT |  | 否 |
| output_event | TEXT |  | 是 |
| enabled | INTEGER |  | 是 |
| fired_count | INTEGER |  | 是 |
| last_fired | TEXT |  | 是 |
| description | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_trigger_handler (89 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| handler_id | TEXT | ✓ | 是 |
| trigger_event_type | TEXT |  | 否 |
| handler_key | TEXT |  | 否 |
| target_engine | TEXT |  | 否 |
| target_method | TEXT |  | 否 |
| enabled | INTEGER |  | 是 |
| phase | INTEGER |  | 是 |
| last_executed | TEXT |  | 是 |
| last_success | INTEGER |  | 是 |
| exec_count | INTEGER |  | 是 |
| avg_duration_ms | REAL |  | 是 |

### mt_trigger_health_check (423 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| health_id | TEXT | ✓ | 是 |
| check_time | TEXT |  | 是 |
| total_triggers | INTEGER |  | 是 |
| active_triggers | INTEGER |  | 是 |
| total_handlers | INTEGER |  | 是 |
| enabled_handlers | INTEGER |  | 是 |
| event_count_1h | INTEGER |  | 是 |
| success_rate | REAL |  | 是 |
| avg_latency_ms | REAL |  | 是 |
| throttle_events | INTEGER |  | 是 |
| retry_queue_count | INTEGER |  | 是 |
| dlq_count | INTEGER |  | 是 |
| global_switches_json | TEXT |  | 是 |
| health_score | REAL |  | 是 |
| overall_status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_trigger_registry (19 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| trigger_id | TEXT | ✓ | 是 |
| event_type | TEXT |  | 否 |
| priority | TEXT |  | 是 |
| cooldown_ms | INTEGER |  | 是 |
| handler_count | INTEGER |  | 是 |
| enabled | INTEGER |  | 是 |
| throttle_max_per_sec | INTEGER |  | 是 |
| throttle_burst | INTEGER |  | 是 |
| description | TEXT |  | 是 |
| registered_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_ts_chat (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| chat_id | TEXT | ✓ | 是 |
| team_id | TEXT |  | 否 |
| teacher_id | TEXT |  | 是 |
| role | TEXT |  | 是 |
| message | TEXT |  | 否 |
| context_json | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_ts_competency (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| comp_id | TEXT | ✓ | 是 |
| teacher_id | TEXT |  | 否 |
| team_id | TEXT |  | 是 |
| dimension | TEXT |  | 否 |
| score | REAL |  | 是 |
| delta | REAL |  | 是 |
| evidence | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_ts_lesson_plan (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| plan_id | TEXT | ✓ | 是 |
| team_id | TEXT |  | 否 |
| teacher_id | TEXT |  | 否 |
| title | TEXT |  | 否 |
| subject | TEXT |  | 是 |
| grade | TEXT |  | 是 |
| duration_min | INTEGER |  | 是 |
| objectives | TEXT |  | 是 |
| plan_content | TEXT |  | 是 |
| key_points | TEXT |  | 是 |
| difficult_points | TEXT |  | 是 |
| teaching_method | TEXT |  | 是 |
| ollama_feedback | TEXT |  | 是 |
| feedback_dimensions | TEXT |  | 是 |
| overall_score | REAL |  | 是 |
| created_at | TEXT |  | 是 |

### mt_ts_mock_class (3 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| mock_id | TEXT | ✓ | 是 |
| plan_id | TEXT |  | 否 |
| team_id | TEXT |  | 否 |
| teacher_id | TEXT |  | 否 |
| student_type | TEXT |  | 是 |
| student_persona | TEXT |  | 是 |
| reaction | TEXT |  | 是 |
| question_raised | TEXT |  | 是 |
| confusion_spot | TEXT |  | 是 |
| engagement_score | REAL |  | 是 |
| understanding_score | REAL |  | 是 |
| created_at | TEXT |  | 是 |

### mt_ts_reflection (3 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| ref_id | TEXT | ✓ | 是 |
| team_id | TEXT |  | 否 |
| plan_id | TEXT |  | 是 |
| teacher_id | TEXT |  | 是 |
| reflection_type | TEXT |  | 是 |
| content | TEXT |  | 是 |
| strengths_json | TEXT |  | 是 |
| improvements_json | TEXT |  | 是 |
| competency_shift_json | TEXT |  | 是 |
| brain_feed_ids | TEXT |  | 是 |
| created_by | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_ts_teacher (42 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| teacher_id | TEXT | ✓ | 是 |
| team_id | TEXT |  | 否 |
| name | TEXT |  | 否 |
| subject | TEXT |  | 是 |
| role | TEXT |  | 是 |
| is_ai | INTEGER |  | 是 |
| ai_employee_id | TEXT |  | 是 |
| level | REAL |  | 是 |
| total_score | REAL |  | 是 |
| lessons_done | INTEGER |  | 是 |
| reflections_done | INTEGER |  | 是 |
| join_at | TEXT |  | 是 |

### mt_tx_pool (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| tx_id | INTEGER | ✓ | 是 |
| tx_hash | TEXT |  | 否 |
| tx_type | TEXT |  | 否 |
| sender | TEXT |  | 是 |
| payload | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| status | TEXT |  | 是 |
| block_height | INTEGER |  | 是 |

### mt_user_theme_preferences (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| user_id | TEXT |  | 否 |
| theme_mode | TEXT |  | 是 |
| auto_switch | INTEGER |  | 是 |
| preset_name | TEXT |  | 是 |
| custom_primary | TEXT |  | 是 |
| custom_secondary | TEXT |  | 是 |
| custom_accent | TEXT |  | 是 |
| bg_image_url | TEXT |  | 是 |
| bg_opacity | REAL |  | 是 |
| bg_type | TEXT |  | 是 |
| sunrise_time | TEXT |  | 是 |
| sunset_time | TEXT |  | 是 |
| latitude | REAL |  | 是 |
| longitude | REAL |  | 是 |
| city_name | TEXT |  | 是 |
| memorial_lock | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_user_token_accounts (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| user_id | INTEGER | ✓ | 是 |
| username | TEXT |  | 否 |
| balance | INTEGER |  | 否 |
| last_grant_date | TEXT |  | 是 |
| total_granted | INTEGER |  | 否 |
| total_consumed | INTEGER |  | 否 |
| total_preheld | INTEGER |  | 否 |
| total_rewarded | INTEGER |  | 否 |
| updated_at | TEXT |  | 是 |

### mt_user_token_ledger (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| user_id | INTEGER |  | 否 |
| change | INTEGER |  | 否 |
| type | TEXT |  | 否 |
| session_id | TEXT |  | 是 |
| model | TEXT |  | 是 |
| detail | TEXT |  | 是 |
| balance_after | INTEGER |  | 否 |
| created_at | TEXT |  | 是 |

### mt_vault_alert (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| alert_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 是 |
| alert_type | TEXT |  | 否 |
| level | TEXT |  | 是 |
| title | TEXT |  | 否 |
| description | TEXT |  | 是 |
| trade_ids | TEXT |  | 是 |
| symbol | TEXT |  | 是 |
| metric_value | REAL |  | 是 |
| threshold | REAL |  | 是 |
| verdict | TEXT |  | 是 |
| resolved_by | TEXT |  | 是 |
| resolved_at | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_vault_attribution (147 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| attr_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| attr_type | TEXT |  | 否 |
| attr_date | TEXT |  | 是 |
| symbol | TEXT |  | 是 |
| industry | TEXT |  | 是 |
| metric | TEXT |  | 否 |
| value | REAL |  | 是 |
| details | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_vault_audit_log (10,531 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| audit_id | TEXT | ✓ | 是 |
| audit_type | TEXT |  | 否 |
| dimension | TEXT |  | 否 |
| level | TEXT |  | 是 |
| session_id | TEXT |  | 是 |
| symbol | TEXT |  | 是 |
| trade_id | TEXT |  | 是 |
| description | TEXT |  | 是 |
| expected | TEXT |  | 是 |
| actual | TEXT |  | 是 |
| diff_pct | REAL |  | 是 |
| verdict | TEXT |  | 是 |
| operator | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| resolved | INTEGER |  | 是 |
| resolved_at | TEXT |  | 是 |
| resolution_note | TEXT |  | 是 |
**外键:**
| 本地列 | → 目标表 | 目标列 |
|--------|---------|--------|
| trade_id | mt_sandbox_trades | trade_id |

### mt_vault_balance_sheet (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| bs_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| report_date | TEXT |  | 否 |
| total_assets | REAL |  | 是 |
| cash | REAL |  | 是 |
| receivables | REAL |  | 是 |
| positions_market_value | REAL |  | 是 |
| positions_cost | REAL |  | 是 |
| payables | REAL |  | 是 |
| margin_debt | REAL |  | 是 |
| total_liabilities | REAL |  | 是 |
| capital | REAL |  | 是 |
| accumulated_pnl | REAL |  | 是 |
| current_pnl | REAL |  | 是 |
| total_equity | REAL |  | 是 |
| is_balanced | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_vault_cash_flow (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| cash_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| period | TEXT |  | 否 |
| activity_type | TEXT |  | 否 |
| sub_type | TEXT |  | 是 |
| inflow | REAL |  | 是 |
| outflow | REAL |  | 是 |
| net | REAL |  | 是 |
| transaction_count | INTEGER |  | 是 |
| counterparty | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_vault_counterparty (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| cp_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| name | TEXT |  | 否 |
| type | TEXT |  | 是 |
| trade_count | INTEGER |  | 是 |
| total_volume | REAL |  | 是 |
| total_fees | REAL |  | 是 |
| total_trades | REAL |  | 是 |
| last_trade | TEXT |  | 是 |

### mt_vault_dividend (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| div_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| symbol | TEXT |  | 否 |
| ex_date | TEXT |  | 否 |
| dividend_per_share | REAL |  | 是 |
| split_ratio | REAL |  | 是 |
| qty_before | INTEGER |  | 是 |
| qty_after | INTEGER |  | 是 |
| cash_received | REAL |  | 是 |
| created_at | TEXT |  | 是 |

### mt_vault_income_stmt (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| income_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| period | TEXT |  | 否 |
| realized_pnl | REAL |  | 是 |
| unrealized_pnl_change | REAL |  | 是 |
| fees_income | REAL |  | 是 |
| total_revenue | REAL |  | 是 |
| commissions | REAL |  | 是 |
| stamp_taxes | REAL |  | 是 |
| transfer_fees | REAL |  | 是 |
| total_expenses | REAL |  | 是 |
| gross_profit | REAL |  | 是 |
| net_profit | REAL |  | 是 |
| net_profit_pct | REAL |  | 是 |
| created_at | TEXT |  | 是 |

### mt_vault_journal (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| journal_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| voucher_no | TEXT |  | 否 |
| trade_id | TEXT |  | 是 |
| journal_date | TEXT |  | 否 |
| summary | TEXT |  | 是 |
| account_code | TEXT |  | 否 |
| account_name | TEXT |  | 否 |
| debit | REAL |  | 是 |
| credit | REAL |  | 是 |
| entry_seq | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_vault_ledger (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| ledger_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| account_code | TEXT |  | 否 |
| account_name | TEXT |  | 否 |
| account_type | TEXT |  | 否 |
| balance | REAL |  | 是 |
| debit | REAL |  | 是 |
| credit | REAL |  | 是 |
| period | TEXT |  | 否 |
| updated_at | TEXT |  | 是 |

### mt_vault_positions (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| position_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| symbol | TEXT |  | 否 |
| stock_name | TEXT |  | 是 |
| industry | TEXT |  | 是 |
| market | TEXT |  | 是 |
| qty | INTEGER |  | 是 |
| avg_cost | REAL |  | 是 |
| total_cost | REAL |  | 是 |
| last_price | REAL |  | 是 |
| market_value | REAL |  | 是 |
| unrealized_pnl | REAL |  | 是 |
| unrealized_pnl_pct | REAL |  | 是 |
| weight_pct | REAL |  | 是 |
| open_date | TEXT |  | 是 |
| last_update | TEXT |  | 是 |

### mt_vault_risk_snapshot (16 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| risk_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| snap_date | TEXT |  | 否 |
| var_95 | REAL |  | 是 |
| cvar_95 | REAL |  | 是 |
| sharpe | REAL |  | 是 |
| calmar | REAL |  | 是 |
| sortino | REAL |  | 是 |
| win_rate | REAL |  | 是 |
| profit_factor | REAL |  | 是 |
| max_drawdown | REAL |  | 是 |
| turnover | REAL |  | 是 |
| beta | REAL |  | 是 |
| risk_score | REAL |  | 是 |
| risk_level | TEXT |  | 是 |
| total_return | REAL |  | 是 |
| annualized_return | REAL |  | 是 |
| annualized_volatility | REAL |  | 是 |
| trade_count | INTEGER |  | 是 |
| up_days | INTEGER |  | 是 |

### mt_vault_trades (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| vault_trade_id | TEXT | ✓ | 是 |
| source_trade_id | TEXT |  | 是 |
| session_id | TEXT |  | 否 |
| trade_date | TEXT |  | 否 |
| trade_time | TEXT |  | 是 |
| symbol | TEXT |  | 否 |
| stock_name | TEXT |  | 是 |
| action | TEXT |  | 否 |
| shares | INTEGER |  | 否 |
| price | REAL |  | 否 |
| gross_amount | REAL |  | 是 |
| commission | REAL |  | 是 |
| stamp_tax | REAL |  | 是 |
| transfer_fee | REAL |  | 是 |
| net_amount | REAL |  | 是 |
| counterparty | TEXT |  | 是 |
| market | TEXT |  | 是 |
| industry | TEXT |  | 是 |
| account_type | TEXT |  | 是 |
| journal_seq | INTEGER |  | 是 |
**外键:**
| 本地列 | → 目标表 | 目标列 |
|--------|---------|--------|
| source_trade_id | mt_sandbox_trades | trade_id |

### mt_vault_transfer (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| transfer_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 否 |
| transfer_date | TEXT |  | 否 |
| transfer_type | TEXT |  | 否 |
| amount | REAL |  | 否 |
| direction | TEXT |  | 否 |
| counterparty | TEXT |  | 是 |
| fee | REAL |  | 是 |
| balance_after | REAL |  | 是 |
| notes | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_vault_watchlist (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| watch_id | TEXT | ✓ | 是 |
| session_id | TEXT |  | 是 |
| symbol | TEXT |  | 否 |
| stock_name | TEXT |  | 是 |
| industry | TEXT |  | 是 |
| source | TEXT |  | 是 |
| added_at | TEXT |  | 是 |

### mt_version_registry (1 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| version_code | TEXT |  | 否 |
| version_name | TEXT |  | 是 |
| version_number | TEXT |  | 是 |
| description | TEXT |  | 是 |
| milestone_date | DATE |  | 是 |
| is_active | INTEGER |  | 是 |
| created_at | DATETIME |  | 是 |

### mt_wecom_commands (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| cmd | TEXT |  | 否 |
| args_json | TEXT |  | 是 |
| source | TEXT |  | 是 |
| operator | TEXT |  | 是 |
| status | TEXT |  | 是 |
| result_md | TEXT |  | 是 |
| error | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| executed_at | TEXT |  | 是 |

### mt_wecom_config (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| key | TEXT | ✓ | 是 |
| value | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |
| updated_by | TEXT |  | 是 |

### mt_wecom_meetings (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| topic | TEXT |  | 否 |
| minutes_md | TEXT |  | 否 |
| stats_json | TEXT |  | 是 |
| attendees | TEXT |  | 是 |
| push_status | TEXT |  | 是 |
| convener | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_wecom_send_log (884 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| center | TEXT |  | 否 |
| title | TEXT |  | 否 |
| content | TEXT |  | 是 |
| status | TEXT |  | 是 |
| resp_code | INTEGER |  | 是 |
| error | TEXT |  | 是 |
| operator | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_wflow_definition (2 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| wflow_id | TEXT | ✓ | 是 |
| name | TEXT |  | 是 |
| description | TEXT |  | 是 |
| steps | TEXT |  | 是 |
| failure_paths | TEXT |  | 是 |
| trigger_event | TEXT |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_wflow_instance (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| instance_id | TEXT | ✓ | 是 |
| wflow_id | TEXT |  | 是 |
| wflow_name | TEXT |  | 是 |
| current_step | INTEGER |  | 是 |
| current_status | TEXT |  | 是 |
| task_id | INTEGER |  | 是 |
| task_title | TEXT |  | 是 |
| assigned_center | TEXT |  | 是 |
| priority | TEXT |  | 是 |
| status | TEXT |  | 是 |
| started_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |
| completed_at | TEXT |  | 是 |
| escalated_to | TEXT |  | 是 |

### mt_wflow_step_log (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| instance_id | TEXT |  | 是 |
| step_order | INTEGER |  | 是 |
| step_name | TEXT |  | 是 |
| step_action | TEXT |  | 是 |
| handler | TEXT |  | 是 |
| center | TEXT |  | 是 |
| status | TEXT |  | 是 |
| started_at | TEXT |  | 是 |
| completed_at | TEXT |  | 是 |
| error_msg | TEXT |  | 是 |
| elapsed_sec | REAL |  | 是 |

### mt_writing_fandom (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| project_id | INTEGER |  | 否 |
| fandom_type | TEXT |  | 是 |
| source_ip | TEXT |  | 是 |
| characters | TEXT |  | 是 |
| relationship_map | TEXT |  | 是 |
| tag | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_writing_iteration (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| project_id | INTEGER |  | 是 |
| iteration | INTEGER |  | 是 |
| content | TEXT |  | 是 |
| prompt_used | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
**外键:**
| 本地列 | → 目标表 | 目标列 |
|--------|---------|--------|
| project_id | mt_writing_project | id |

### mt_writing_project (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| title | TEXT |  | 是 |
| core_idea | TEXT |  | 是 |
| genre | TEXT |  | 是 |
| audience | TEXT |  | 是 |
| word_count | INTEGER |  | 是 |
| model_used | TEXT |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mtscos_ai_employees (23 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| uid | TEXT |  | 否 |
| name | TEXT |  | 否 |
| role | TEXT |  | 是 |
| dept | TEXT |  | 是 |
| expertise_json | TEXT |  | 是 |
| skills_json | TEXT |  | 是 |
| scores_json | TEXT |  | 是 |
| salary_tokens_per_hour | REAL |  | 是 |
| approval_note | TEXT |  | 是 |
| linked_approval_id | INTEGER |  | 是 |
| linked_change_id | TEXT |  | 是 |
| onboarded_at | TEXT |  | 是 |
| onboarded_by | TEXT |  | 是 |
| is_active | INTEGER |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mtscos_version_history (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| version | TEXT |  | 否 |
| major | INTEGER |  | 是 |
| minor | INTEGER |  | 是 |
| patch | INTEGER |  | 是 |
| build | TEXT |  | 是 |
| release_channel | TEXT |  | 是 |
| parent_approval_id | INTEGER |  | 是 |
| parent_change_id | TEXT |  | 是 |
| change_summary | TEXT |  | 是 |
| changelog_json | TEXT |  | 是 |
| git_commit_hash | TEXT |  | 是 |
| git_tag | TEXT |  | 是 |
| github_pushed | INTEGER |  | 是 |
| release_notes_json | TEXT |  | 是 |
| ssot_writeback_ok | INTEGER |  | 是 |
| ssot_readback_ok | INTEGER |  | 是 |
| published_by | TEXT |  | 是 |
| published_at | TEXT |  | 是 |
<!-- AUTO-GENERATED-END:tables -->

## 5. 引擎函数清单
<!-- AUTO-GENERATED-START:functions -->
| 文件 | 类/函数 | 类型 | 参数 | 说明 |
|------|---------|------|------|------|
| andromeda_chat_bp.py | def _ensure | 函数 |  |  |
| andromeda_chat_bp.py | def _u | 函数 |  |  |
| andromeda_chat_bp.py | def _is_sa | 函数 | u |  |
| andromeda_chat_bp.py | def _login_required | 函数 | fn |  |
| andromeda_chat_bp.py | def _visible_session | 函数 | conn, sid, u |  |
| andromeda_chat_bp.py | def _action | 函数 | conn, sid, uid, action, detail |  |
| andromeda_chat_bp.py | def _feed | 函数 | string, target, payload, by |  |
| andromeda_chat_bp.py | def chat_search | 函数 |  |  |
| andromeda_chat_bp.py | def chat_msg_context | 函数 |  | 按 mid 返回前后若干条消息, 供检索结果直接定位到具体消息 |
| andromeda_chat_bp.py | def chat_msg_edit | 函数 | mid |  |
| andromeda_chat_bp.py | def chat_msg_list | 函数 |  |  |
| andromeda_chat_bp.py | def chat_msg_delete | 函数 | mid |  |
| andromeda_chat_bp.py | def chat_msg_feedback | 函数 | mid |  |
| andromeda_chat_bp.py | def chat_session_archive | 函数 | sid |  |
| andromeda_chat_bp.py | def chat_unread | 函数 |  |  |
| andromeda_chat_bp.py | def chat_mark_read | 函数 | sid |  |
| andromeda_chat_bp.py | def chat_export | 函数 | sid |  |
| andromeda_chat_bp.py | def _teams | 函数 | conn |  |
| andromeda_chat_bp.py | def _jump | 函数 | label, kind, key | 生成跳转标记: 前端 linkify 成可点击链接, 导出 md 转 Markd |
| andromeda_chat_bp.py | def _jump_href | 函数 | kind, key |  |
| andromeda_chat_bp.py | def _md_links | 函数 | text | 导出 md 时把 [[jump|标签|kind:key]] 还原为标准 Mark |
| andromeda_chat_bp.py | def chat_jump_resolve | 函数 |  | 把消息里的任务号 / @天团 / 会话号解析成可跳转目标 |
| andromeda_chat_bp.py | def chat_jump_center | 函数 |  | 任务中心详情: 各状态任务数 + 近期任务 (任务大厅中心名可点击进入) |
| andromeda_chat_bp.py | def chat_jump_team | 函数 |  | 天团详情: 名称/关键词/成员/近期承接任务 (供聊天面板内展示, 不跳空白页) |
| andromeda_chat_bp.py | def _chat_only | 函数 | u | 小龙端注册的仅聊天账号: 未开通 full_access 时禁止派单等非聊天能力 |
| andromeda_chat_bp.py | def chat_jump_task | 函数 | task_id | 任务跳转详情: 基础信息 + 状态机轨迹 (供聊天面板内展示) |
| andromeda_chat_bp.py | def chat_plus_meta | 函数 |  |  |
| andromeda_chat_bp.py | def _multi_ai_short | 函数 | raw |  |
| andromeda_chat_bp.py | def _multi_ai_pick | 函数 | conn, text, requested | 返回 (personas, all_team_names)。personas:  |
| andromeda_chat_bp.py | def _multi_ai_ask | 函数 | persona, prompt, system | 单个 AI 本地推理 (并发调用, 不写库) |
| andromeda_chat_bp.py | def chat_multi_ai | 函数 |  | 多人 AI 同时聊: 一条需求 → N 位 AI 并发作答 → 总控收敛 (可选 |
| andromeda_chat_bp.py | def chat_mention | 函数 |  | 把聊天里 @天团 的内容一键派成任务大厅任务, 并回帖系统消息 |
| andromeda_openai_bp.py | def _auth_ok | 函数 |  | Bearer key 校验; 允许无 Authorization (本机回环调试 |
| andromeda_openai_bp.py | def _err | 函数 | msg, code, etype |  |
| andromeda_openai_bp.py | def _split_messages | 函数 | msgs | OpenAI messages → (system, prompt); 多轮历史 |
| andromeda_openai_bp.py | def _ask | 函数 | system, prompt | 调用仙女座统一网关 (本地推理 + 脑库RAG) |
| andromeda_openai_bp.py | def list_models | 函数 |  |  |
| andromeda_openai_bp.py | def chat_completions | 函数 |  |  |
| andromeda_openai_bp.py | def _responses_input | 函数 | body | Responses API 的 input → (system, prompt) |
| andromeda_openai_bp.py | def responses | 函数 |  |  |
| andromeda_stats_bp.py | def _cols | 函数 | c, table |  |
| andromeda_stats_bp.py | def _table_exists | 函数 | c, table |  |
| andromeda_stats_bp.py | def _collect_events | 函数 | c | 归一化全部事件源 → [{time, category, source_tabl |
| andromeda_stats_bp.py | def _collect_gaps | 函数 | c |  |
| andromeda_stats_bp.py | def _collect_teams | 函数 | c |  |
| andromeda_stats_bp.py | def _build_overview | 函数 | c |  |
| andromeda_stats_bp.py | def stats_page | 函数 |  |  |
| andromeda_stats_bp.py | def stats_overview | 函数 |  |  |
| andromeda_stats_bp.py | def stats_events | 函数 |  |  |
| andromeda_stats_bp.py | def stats_dispatch | 函数 |  | 缺口 → 研发联动: 写入 smart_mount 建议池(mt_ai_sugg |
| collab_bus_bp.py | def _ensure_subscribers | 函数 |  | 确保 11+1=12 家订阅者已注册, 自修复钩子 |
| collab_bus_bp.py | def api_status | 函数 |  | 协作总线状态概览 |
| collab_bus_bp.py | def api_events | 函数 |  | 获取事件历史
query params:
- limit: 默认 50, 最大  |
| collab_bus_bp.py | def api_subscribers | 函数 |  | 所有订阅者 |
| collab_bus_bp.py | def api_publish | 函数 |  | 发布事件到协作总线
body JSON:
{
    "event_type": |
| collab_bus_bp.py | def api_radar_cache | 函数 |  | 市场雷达当前缓存 |
| collab_bus_bp.py | def api_start_radar | 函数 |  | 启动市场雷达 daemon
body JSON: {"cycle": 5} |
| collab_bus_bp.py | def api_version_components | 函数 |  | 所有组件当前版本 |
| collab_bus_bp.py | def api_version_history | 函数 |  | 版本历史
query params:
- component: 可选
- lim |
| collab_bus_bp.py | def api_version_bump | 函数 |  | 手动触发版本 bump
body JSON:
{"component": "an |
| andromeda_chat_bp.py | def _ensure | 函数 |  |  |
| andromeda_chat_bp.py | def _u | 函数 |  |  |
| andromeda_chat_bp.py | def _is_sa | 函数 | u |  |
| andromeda_chat_bp.py | def _login_required | 函数 | fn |  |
| andromeda_chat_bp.py | def _visible_session | 函数 | conn, sid, u |  |
| andromeda_chat_bp.py | def _action | 函数 | conn, sid, uid, action, detail |  |
| andromeda_chat_bp.py | def _feed | 函数 | string, target, payload, by |  |
| andromeda_chat_bp.py | def chat_search | 函数 |  |  |
| andromeda_chat_bp.py | def chat_msg_context | 函数 |  | 按 mid 返回前后若干条消息, 供检索结果直接定位到具体消息 |
| andromeda_chat_bp.py | def chat_msg_edit | 函数 | mid |  |
| andromeda_chat_bp.py | def chat_msg_list | 函数 |  |  |
| andromeda_chat_bp.py | def chat_msg_delete | 函数 | mid |  |
| andromeda_chat_bp.py | def chat_msg_feedback | 函数 | mid |  |
| andromeda_chat_bp.py | def chat_session_archive | 函数 | sid |  |
| andromeda_chat_bp.py | def chat_unread | 函数 |  |  |
| andromeda_chat_bp.py | def chat_mark_read | 函数 | sid |  |
| andromeda_chat_bp.py | def chat_export | 函数 | sid |  |
| andromeda_chat_bp.py | def _teams | 函数 | conn |  |
| andromeda_chat_bp.py | def _jump | 函数 | label, kind, key | 生成跳转标记: 前端 linkify 成可点击链接, 导出 md 转 Markd |
| andromeda_chat_bp.py | def _jump_href | 函数 | kind, key |  |
| andromeda_chat_bp.py | def _md_links | 函数 | text | 导出 md 时把 [[jump|标签|kind:key]] 还原为标准 Mark |
| andromeda_chat_bp.py | def chat_jump_resolve | 函数 |  | 把消息里的任务号 / @天团 / 会话号解析成可跳转目标 |
| andromeda_chat_bp.py | def chat_jump_center | 函数 |  | 任务中心详情: 各状态任务数 + 近期任务 (任务大厅中心名可点击进入) |
| andromeda_chat_bp.py | def chat_jump_team | 函数 |  | 天团详情: 名称/关键词/成员/近期承接任务 (供聊天面板内展示, 不跳空白页) |
| andromeda_chat_bp.py | def _chat_only | 函数 | u | 小龙端注册的仅聊天账号: 未开通 full_access 时禁止派单等非聊天能力 |
| andromeda_chat_bp.py | def chat_jump_task | 函数 | task_id | 任务跳转详情: 基础信息 + 状态机轨迹 (供聊天面板内展示) |
| andromeda_chat_bp.py | def chat_plus_meta | 函数 |  |  |
| andromeda_chat_bp.py | def _multi_ai_short | 函数 | raw |  |
| andromeda_chat_bp.py | def _multi_ai_pick | 函数 | conn, text, requested | 返回 (personas, all_team_names)。personas:  |
| andromeda_chat_bp.py | def _multi_ai_ask | 函数 | persona, prompt, system | 单个 AI 本地推理 (并发调用, 不写库) |
| andromeda_chat_bp.py | def chat_multi_ai | 函数 |  | 多人 AI 同时聊: 一条需求 → N 位 AI 并发作答 → 总控收敛 (可选 |
| andromeda_chat_bp.py | def chat_mention | 函数 |  | 把聊天里 @天团 的内容一键派成任务大厅任务, 并回帖系统消息 |
| andromeda_openai_bp.py | def _auth_ok | 函数 |  | Bearer key 校验; 允许无 Authorization (本机回环调试 |
| andromeda_openai_bp.py | def _err | 函数 | msg, code, etype |  |
| andromeda_openai_bp.py | def _split_messages | 函数 | msgs | OpenAI messages → (system, prompt); 多轮历史 |
| andromeda_openai_bp.py | def _ask | 函数 | system, prompt | 调用仙女座统一网关 (本地推理 + 脑库RAG) |
| andromeda_openai_bp.py | def list_models | 函数 |  |  |
| andromeda_openai_bp.py | def chat_completions | 函数 |  |  |
| andromeda_openai_bp.py | def _responses_input | 函数 | body | Responses API 的 input → (system, prompt) |
| andromeda_openai_bp.py | def responses | 函数 |  |  |
| andromeda_stats_bp.py | def _cols | 函数 | c, table |  |
| andromeda_stats_bp.py | def _table_exists | 函数 | c, table |  |
| andromeda_stats_bp.py | def _collect_events | 函数 | c | 归一化全部事件源 → [{time, category, source_tabl |
| andromeda_stats_bp.py | def _collect_gaps | 函数 | c |  |
| andromeda_stats_bp.py | def _collect_teams | 函数 | c |  |
| andromeda_stats_bp.py | def _build_overview | 函数 | c |  |
| andromeda_stats_bp.py | def stats_page | 函数 |  |  |
| andromeda_stats_bp.py | def stats_overview | 函数 |  |  |
| andromeda_stats_bp.py | def stats_events | 函数 |  |  |
| andromeda_stats_bp.py | def stats_dispatch | 函数 |  | 缺口 → 研发联动: 写入 smart_mount 建议池(mt_ai_sugg |
| collab_bus_bp.py | def _ensure_subscribers | 函数 |  | 确保 11+1=12 家订阅者已注册, 自修复钩子 |
| collab_bus_bp.py | def api_status | 函数 |  | 协作总线状态概览 |
| collab_bus_bp.py | def api_events | 函数 |  | 获取事件历史
query params:
- limit: 默认 50, 最大  |
| collab_bus_bp.py | def api_subscribers | 函数 |  | 所有订阅者 |
| collab_bus_bp.py | def api_publish | 函数 |  | 发布事件到协作总线
body JSON:
{
    "event_type": |
| collab_bus_bp.py | def api_radar_cache | 函数 |  | 市场雷达当前缓存 |
| collab_bus_bp.py | def api_start_radar | 函数 |  | 启动市场雷达 daemon
body JSON: {"cycle": 5} |
| collab_bus_bp.py | def api_version_components | 函数 |  | 所有组件当前版本 |
| collab_bus_bp.py | def api_version_history | 函数 |  | 版本历史
query params:
- component: 可选
- lim |
| collab_bus_bp.py | def api_version_bump | 函数 |  | 手动触发版本 bump
body JSON:
{"component": "an |
| andromeda_chat_bp.py | def _ensure | 函数 |  |  |
| andromeda_chat_bp.py | def _u | 函数 |  |  |
| andromeda_chat_bp.py | def _is_sa | 函数 | u |  |
| andromeda_chat_bp.py | def _login_required | 函数 | fn |  |
| andromeda_chat_bp.py | def _visible_session | 函数 | conn, sid, u |  |
| andromeda_chat_bp.py | def _action | 函数 | conn, sid, uid, action, detail |  |
| andromeda_chat_bp.py | def _feed | 函数 | string, target, payload, by |  |
| andromeda_chat_bp.py | def chat_search | 函数 |  |  |
| andromeda_chat_bp.py | def chat_msg_context | 函数 |  | 按 mid 返回前后若干条消息, 供检索结果直接定位到具体消息 |
| andromeda_chat_bp.py | def chat_msg_edit | 函数 | mid |  |
| andromeda_chat_bp.py | def chat_msg_list | 函数 |  |  |
| andromeda_chat_bp.py | def chat_msg_delete | 函数 | mid |  |
| andromeda_chat_bp.py | def chat_msg_feedback | 函数 | mid |  |
| andromeda_chat_bp.py | def chat_session_archive | 函数 | sid |  |
| andromeda_chat_bp.py | def chat_unread | 函数 |  |  |
| andromeda_chat_bp.py | def chat_mark_read | 函数 | sid |  |
| andromeda_chat_bp.py | def chat_export | 函数 | sid |  |
| andromeda_chat_bp.py | def _teams | 函数 | conn |  |
| andromeda_chat_bp.py | def _jump | 函数 | label, kind, key | 生成跳转标记: 前端 linkify 成可点击链接, 导出 md 转 Markd |
| andromeda_chat_bp.py | def _jump_href | 函数 | kind, key |  |
| andromeda_chat_bp.py | def _md_links | 函数 | text | 导出 md 时把 [[jump|标签|kind:key]] 还原为标准 Mark |
| andromeda_chat_bp.py | def chat_jump_resolve | 函数 |  | 把消息里的任务号 / @天团 / 会话号解析成可跳转目标 |
| andromeda_chat_bp.py | def chat_jump_center | 函数 |  | 任务中心详情: 各状态任务数 + 近期任务 (任务大厅中心名可点击进入) |
| andromeda_chat_bp.py | def chat_jump_team | 函数 |  | 天团详情: 名称/关键词/成员/近期承接任务 (供聊天面板内展示, 不跳空白页) |
| andromeda_chat_bp.py | def _chat_only | 函数 | u | 小龙端注册的仅聊天账号: 未开通 full_access 时禁止派单等非聊天能力 |
| andromeda_chat_bp.py | def chat_jump_task | 函数 | task_id | 任务跳转详情: 基础信息 + 状态机轨迹 (供聊天面板内展示) |
| andromeda_chat_bp.py | def chat_plus_meta | 函数 |  |  |
| andromeda_chat_bp.py | def _multi_ai_short | 函数 | raw |  |
| andromeda_chat_bp.py | def _multi_ai_pick | 函数 | conn, text, requested | 返回 (personas, all_team_names)。personas:  |
| andromeda_chat_bp.py | def _multi_ai_ask | 函数 | persona, prompt, system | 单个 AI 本地推理 (并发调用, 不写库) |
| andromeda_chat_bp.py | def chat_multi_ai | 函数 |  | 多人 AI 同时聊: 一条需求 → N 位 AI 并发作答 → 总控收敛 (可选 |
| andromeda_chat_bp.py | def chat_mention | 函数 |  | 把聊天里 @天团 的内容一键派成任务大厅任务, 并回帖系统消息 |
| andromeda_openai_bp.py | def _auth_ok | 函数 |  | Bearer key 校验; 允许无 Authorization (本机回环调试 |
| andromeda_openai_bp.py | def _err | 函数 | msg, code, etype |  |
| andromeda_openai_bp.py | def _split_messages | 函数 | msgs | OpenAI messages → (system, prompt); 多轮历史 |
| andromeda_openai_bp.py | def _ask | 函数 | system, prompt | 调用仙女座统一网关 (本地推理 + 脑库RAG) |
| andromeda_openai_bp.py | def list_models | 函数 |  |  |
| andromeda_openai_bp.py | def chat_completions | 函数 |  |  |
| andromeda_openai_bp.py | def _responses_input | 函数 | body | Responses API 的 input → (system, prompt) |
| andromeda_openai_bp.py | def responses | 函数 |  |  |
| andromeda_stats_bp.py | def _cols | 函数 | c, table |  |
| andromeda_stats_bp.py | def _table_exists | 函数 | c, table |  |
| andromeda_stats_bp.py | def _collect_events | 函数 | c | 归一化全部事件源 → [{time, category, source_tabl |
| andromeda_stats_bp.py | def _collect_gaps | 函数 | c |  |
| andromeda_stats_bp.py | def _collect_teams | 函数 | c |  |
| andromeda_stats_bp.py | def _build_overview | 函数 | c |  |
| andromeda_stats_bp.py | def stats_page | 函数 |  |  |
| andromeda_stats_bp.py | def stats_overview | 函数 |  |  |
| andromeda_stats_bp.py | def stats_events | 函数 |  |  |
| andromeda_stats_bp.py | def stats_dispatch | 函数 |  | 缺口 → 研发联动: 写入 smart_mount 建议池(mt_ai_sugg |
| collab_bus_bp.py | def _login_required | 函数 | fn | collab bus 内部基础设施端点 — 不强制 SA 登录, 但做安全 ch |
| collab_bus_bp.py | def api_bus_status | 函数 |  |  |
| collab_bus_bp.py | def api_bus_events | 函数 |  |  |
| collab_bus_bp.py | def api_publish | 函数 |  |  |
| collab_bus_bp.py | def api_radar_cache | 函数 |  |  |
| collab_bus_bp.py | def api_start | 函数 |  |  |
| collab_bus_bp.py | def api_subscribers | 函数 |  |  |
| collab_bus_bp.py | def register_collab_bp | 函数 | app |  |
| collab_rd_bp.py | def _db_conn | 函数 | readonly |  |
| collab_rd_bp.py | def _collab_engine | 函数 |  |  |
| collab_rd_bp.py | def _rd_engine | 函数 |  |  |
| collab_rd_bp.py | def api_network | 函数 |  | 完整协作网络 — 含孤立中心 + hub 分组 + 统计. |
| collab_rd_bp.py | def api_pacts | 函数 |  | 已签署的协作契约列表. |
| collab_rd_bp.py | def api_rebuild | 函数 |  | POST /api/collab-rd/rebuild — 用 evolutio |
| collab_rd_bp.py | def api_suggest | 函数 |  | POST /api/collab-rd/suggest — AI 推荐新协作对. |
| collab_rd_bp.py | def api_pact | 函数 |  | POST /api/collab-rd/pact — 签署协作契约.
body: |
| collab_rd_bp.py | def api_hub_network | 函数 |  | POST /api/collab-rd/hub-network — 建立星系 h |
| collab_rd_bp.py | def api_rd_pipeline | 函数 |  | 研发流水线总览状态. |
| collab_rd_bp.py | def api_rd_derivatives | 函数 |  | 研发衍生池列表 (分页 + 筛选). |
| collab_rd_bp.py | def api_rd_derive | 函数 |  | POST /api/collab-rd/rd/derive — 从中心职责衍生研 |
| collab_rd_bp.py | def api_rd_compose | 函数 |  | POST /api/collab-rd/rd/compose — 技能链组合. |
| collab_rd_bp.py | def api_rd_sprint | 函数 |  | POST /api/collab-rd/rd/sprint — 周末研发冲刺. |
| collab_rd_bp.py | def api_rd_feedback | 函数 |  | POST /api/collab-rd/rd/feedback — 研发反馈闭环 |
| collab_rd_bp.py | def api_rd_full_cycle | 函数 |  | POST /api/collab-rd/rd/full-cycle — 完整研发 |
| collab_rd_bp.py | def api_dashboard_overview | 函数 |  | GET /api/collab-rd/dashboard/overview —  |
| collab_rd_bp.py | def api_dashboard_network_gr | 函数 |  | GET /api/collab-rd/dashboard/network-gra |
| collab_rd_bp.py | def api_dashboard_rd_pipelin | 函数 |  | GET /api/collab-rd/dashboard/rd-pipeline |
| collab_rd_bp.py | def api_dashboard_feedback | 函数 |  | GET /api/collab-rd/dashboard/feedback —  |
| collab_rd_bp.py | def api_dashboard_health | 函数 |  | GET /api/collab-rd/dashboard/health — 综合 |
| collab_rd_bp.py | def _health_recommendations | 函数 | scores, total | 基于各项分数给出建议. |
| andromeda_warden.py | def _scan_port | 函数 | port, health_url | 扫描端口 + 可选 HTTP health |
| andromeda_warden.py | def _scan_launchd | 函数 | subsys | 扫描 launchd 进程 + DB 数据新鲜度 |
| andromeda_warden.py | def _scan_process | 函数 | subsys |  |
| andromeda_warden.py | def _record_failure | 函数 | key, reason |  |
| andromeda_warden.py | def _should_heal | 函数 | key | 窗口内连续 ≥N 次失败 + 冷却已过 → 可以自愈 |
| andromeda_warden.py | def _heal | 函数 | subsys, scan_result | AI 接管: 按 tier 执行自愈 |
| andromeda_warden.py | def _record_health | 函数 | key, ok |  |
| andromeda_warden.py | def scan_all | 函数 |  | 扫描所有子系统 + 资源层 + 触发自愈 |
| andromeda_warden.py | def health_endpoint | 函数 |  | 供 Flask /api/sandbox/warden/status 调用 |
| andromeda_warden.py | def run | 函数 |  | 主守护循环 |
| andromeda_warden.py | def _save_state | 函数 |  |  |
| andromeda_warden.py | def _load_state | 函数 |  |  |
| andromeda_warden.py | def _scan_resources | 函数 |  | macOS CPU / 内存 / 磁盘 使用情况 |
| andromeda_warden.py | def _scan_port | 函数 | port, health_url | 扫描端口 + 可选 HTTP health |
| andromeda_warden.py | def _scan_launchd | 函数 | subsys | 扫描 launchd 进程 + DB 数据新鲜度 |
| andromeda_warden.py | def _scan_process | 函数 | subsys |  |
| andromeda_warden.py | def _record_failure | 函数 | key, reason |  |
| andromeda_warden.py | def _should_heal | 函数 | key | 窗口内连续 ≥N 次失败 + 冷却已过 → 可以自愈 |
| andromeda_warden.py | def _heal | 函数 | subsys, scan_result | AI 接管: 按 tier 执行自愈 |
| andromeda_warden.py | def _record_health | 函数 | key, ok |  |
| andromeda_warden.py | def scan_all | 函数 |  | 扫描所有子系统 + 触发自愈 |
| andromeda_warden.py | def health_endpoint | 函数 |  | 供 Flask /api/sandbox/warden/status 调用 |
| andromeda_warden.py | def run | 函数 |  | 主守护循环 |
| collab_bus_engine.py | **class CollabBus** | 类 | | 事件总线 — 多中心协作中枢 |
| | ↳ def __new__ | 方法 | cls |  |
| | ↳ def subscribe | 方法 | self, subscriber_id, name, han |  |
| | ↳ def unsubscribe | 方法 | self, subscriber_id |  |
| | ↳ def publish | 方法 | self, event_type, source, payl | 广播事件 — 所有匹配的 subscriber 并发响应
每个 subscrib |
| collab_bus_engine.py | **class MarketRadarDaemon** | 类 | | 实时行情雷达 — 5s poll → 异动检测 → 广播事件 |
| | ↳ def __init__ | 方法 | self, watchlist, cycle_seconds |  |
| | ↳ def start | 方法 | self |  |
| | ↳ def _loop | 方法 | self |  |
| | ↳ def _poll_once | 方法 | self, emit | 一次 poll — 拉新浪实时行情 + 异动检测 + 广播 |
| | ↳ def _sina_batch | 方法 | self, symbols | 新浪实时行情批量拉取 (零依赖 — 纯 urllib) |
| | ↳ def _auto_trigger_stock_skil | 方法 | self, symbol, name, anomaly, c | 异动 → 自动触发证券天团会诊 → 入厅 tick 结案 |
| collab_bus_engine.py | def _db | 函数 |  |  |
| collab_bus_engine.py | def _ensure_tables | 函数 |  |  |
| collab_bus_engine.py | def _log | 函数 | msg |  |
| collab_bus_engine.py | def _submit_event_to_hall | 函数 | event, bus_results | 协作总线事件 → mt_lab_task_hall 自动入厅 (带去重 + 完结 |
| collab_bus_engine.py | def register_all_subscribers | 函数 |  | 一次性注册所有仙女座中心到协作总线 |
| collab_bus_engine.py | def start_collab_platform | 函数 | watchlist, cycle_seconds | 启动协作平台 (Market Radar + Collab Bus 所有订阅中心 |
| collab_bus_engine.py | def get_bus_status | 函数 |  | 协作总线状态 |
| collab_bus_engine.py | def publish_manual | 函数 | event_type, source, payload, s | 手动发布事件 (REST 端点用) |
| collab_bus_engine.py | def get_recent_events | 函数 | limit, event_type | 最近事件 |
| collab_bus_engine.py | def get_radar_cache | 函数 | limit, only_anomalies | 市场雷达缓存 |
| ai_center_self_drive_eng | def _get_all_centers | 函数 |  | 运行时动态获取所有中心 (去重, 稳定顺序: 先 CENTER_PROFILES |
| ai_center_self_drive_eng | def _db | 函数 |  |  |
| ai_center_self_drive_eng | def install_schema | 函数 |  | 建表 + 注册守护 + 写启动日志 (幂等) |
| ai_center_self_drive_eng | def _count_hall_queue | 函数 | c, center_name | 中心认领的大厅积压数 |
| ai_center_self_drive_eng | def _count_active_tasks | 函数 | c, center_name |  |
| ai_center_self_drive_eng | def _count_active_directions | 函数 | c, center_name |  |
| ai_center_self_drive_eng | def pulse_center | 函数 | c, center_name | 单个中心心跳 |
| ai_center_self_drive_eng | def pulse_all | 函数 |  | 14 中心全心跳 |
| ai_center_self_drive_eng | def _report_stale_to_hall | 函数 | c, center_name, table, desc, a | TABLE_FRESHNESS FAIL → 自动上报任务大厅 (24h 去重, |
| ai_center_self_drive_eng | def _check_table_freshness | 函数 | c, center_name, table, desc, s | 检查表最近产出新鲜度 |
| ai_center_self_drive_eng | def self_check_center | 函数 | c, center_name | 单个中心自检 |
| ai_center_self_drive_eng | def self_check_all | 函数 |  |  |
| ai_center_self_drive_eng | def trigger_self_repair | 函数 | c, center_name, table, desc, r | 触发自愈: 直接写任务大厅 + 留痕 |
| ai_center_self_drive_eng | def _upgrade_seed_to_active | 函数 | c, center_name, max_directions | 把方向池 SEED 升级为 ACTIVE (每轮最多升 max_directio |
| ai_center_self_drive_eng | def _rnd_auto_dispatch | 函数 | c, center_name, max_tasks | ACTIVE 方向 → 自动出 mini-plan → 灌任务大厅 |
| ai_center_self_drive_eng | def _rnd_collect_done | 函数 | c, center_name | EXECUTING 方向 → 查大厅 DONE → 升级 phase=DONE  |
| ai_center_self_drive_eng | def rnd_cycle_center | 函数 | c, center_name | 单个中心自研发循环: 升级 SEED → 自动灌单 → 收集 DONE |
| ai_center_self_drive_eng | def rnd_cycle_all | 函数 |  |  |
| ai_center_self_drive_eng | def run_once | 函数 |  | 一轮完整驱动: 心跳 + 自检 + 自愈 + 自研发

每次进入 run_onc |
| ai_center_self_drive_eng | def loop | 函数 | poll_secs |  |
| ai_center_self_drive_eng | def show_centers | 函数 |  |  |
| ai_eigenflux_network_eng | **class AINode** | 类 | |  |
| ai_eigenflux_network_eng | **class AIEigenFluxDaemon** | 类 | |  |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def read_pid | 方法 |  |  |
| | ↳ def write_pid | 方法 |  |  |
| | ↳ def clear_pid | 方法 |  |  |
| | ↳ def reap_stale_pid | 方法 |  | 若PID文件存在但对应进程不存在（典型: 系统重启后残留PID、kill -9硬 |
| | ↳ def is_running | 方法 |  |  |
| | ↳ def ensure_runtime_writable | 方法 |  | 启动前硬性验证 _runtime/{pids,logs,databases/Da |
| | ↳ def start | 方法 | self, once |  |
| | ↳ def stop | 方法 | self |  |
| | ↳ def _wrap_thread | 方法 | self, name, func, interval |  |
| | ↳ def _next_round | 方法 | self |  |
| | ↳ def _heartbeat_thread | 方法 | self |  |
| | ↳ def _handshake_thread | 方法 | self |  |
| | ↳ def _chat_thread | 方法 | self |  |
| | ↳ def _run_once | 方法 | self |  |
| ai_eigenflux_network_eng | def get_conn | 函数 |  |  |
| ai_eigenflux_network_eng | def ensure_tables | 函数 |  |  |
| ai_eigenflux_network_eng | def load_all_ai_nodes | 函数 |  |  |
| ai_eigenflux_network_eng | def ensure_eigenflux_registr | 函数 | nodes | 确保全部 AI 节点在 eigenflux_registrations 有记录( |
| ai_eigenflux_network_eng | def _heartbeat_round | 函数 | nodes, round_no, reconnect_map |  |
| ai_eigenflux_network_eng | def _node_text | 函数 | node |  |
| ai_eigenflux_network_eng | def _conn_uid | 函数 | a, b |  |
| ai_eigenflux_network_eng | def _score_match | 函数 | a, b, topic_tags |  |
| ai_eigenflux_network_eng | def _level_by_score | 函数 | score |  |
| ai_eigenflux_network_eng | def _handshake_round | 函数 | nodes, round_no |  |
| ai_eigenflux_network_eng | def _repair_broken_connectio | 函数 | round_no | 修复BROKEN连接 → CONNECTED (Bug fix: 旧代码只标记B |
| ai_eigenflux_network_eng | def _cleanup_heartbeat_log | 函数 |  | 清理心跳日志表: 保留最近7天数据 (Bug fix: 13M记录无限增长) |
| ai_eigenflux_network_eng | def _pick_topic_for_conn | 函数 | shared_topics_json |  |
| ai_eigenflux_network_eng | def _run_chat_between | 函数 | conn, a, b, topic_key, topic_c |  |
| ai_eigenflux_network_eng | def _learning_session | 函数 | conn, a, b, topic_key, topic_c | 结构化学习会话: 提问 -> 解答 -> 沉淀
每次会话产生 3 条消息 (LE |
| ai_eigenflux_network_eng | def _feed_experience_to_brai | 函数 | conn, sender_name, receiver_na | v2.0: 学习会话强制投喂脑库 (不受 learning_value>=0.5 |
| ai_eigenflux_network_eng | def _ensure_full_coverage | 函数 | nodes, round_no | 找出从未出现在 mt_ai_eigenflux_connections 的孤立  |
| ai_eigenflux_network_eng | def _sync_eigenflux_side_cou | 函数 |  | 把新表消息/会话计数同步回 eigenflux_registrations 既有 |
| ai_eigenflux_network_eng | def _chat_round | 函数 | nodes, round_no |  |
| ai_eigenflux_network_eng | def _detect_offline_and_plan | 函数 | nodes, round_no |  |
| ai_eigenflux_network_eng | def main | 函数 |  |  |
| ai_eigenflux_network_eng | def _feed_experience_to_brai | 函数 | conn, sender_name, receiver_na | 将高价值交流消息自动投喂到 mt_ai_brain_feed_log (AI脑库 |
| ai_eigenflux_network_eng | def _score_message_quality | 函数 | content | 根据消息内容智能评分 (0.1~0.9)
- 含量化指标(+18%, -38%等 |
| ai_eigenflux_network_eng | def _smart_topic_match | 函数 | a, b | 根据两个AI节点的能力/专长智能匹配最佳话题
返回: (topic_key, t |
| ai_eigenflux_network_eng | def _analyze_sentiment | 函数 | content | 简单情感分析: POSITIVE / NEUTRAL / NEGATIVE |
| ai_eigenflux_network_eng | def _update_connection_senti | 函数 | conn, conn_uid, sentiment, lea | 更新连接的情感统计和关系强度 |
| ai_patrol_eigenflux_advi | **class PatrolAdvisorDaemon** | 类 | |  |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def read_pid | 方法 |  |  |
| | ↳ def write_pid | 方法 |  |  |
| | ↳ def clear_pid | 方法 |  |  |
| | ↳ def reap_stale_pid | 方法 |  |  |
| | ↳ def is_running | 方法 |  |  |
| | ↳ def start | 方法 | self, once |  |
| | ↳ def stop | 方法 | self |  |
| ai_patrol_eigenflux_advi | def get_conn | 函数 |  |  |
| ai_patrol_eigenflux_advi | def ensure_tables | 函数 |  |  |
| ai_patrol_eigenflux_advi | def collect_recent_findings | 函数 | hours_back | 从巡检引擎和深度巡检引擎的数据库记录中收集最近发现。
适配实际表名: patro |
| ai_patrol_eigenflux_advi | def route_to_expert | 函数 | finding | 根据发现类型路由到最匹配的 EigenFlux 专家 |
| ai_patrol_eigenflux_advi | def generate_advice_request | 函数 | finding, expert_name, expert_d | 基于实际发现内容生成咨询请求 (非模板) |
| ai_patrol_eigenflux_advi | def generate_expert_advice | 函数 | finding, advice_key | 从知识库中选取匹配的建议, 增加上下文信息 |
| ai_patrol_eigenflux_advi | def score_advice_quality | 函数 | finding, advice | 对建议进行质量评分 0.0-1.0 |
| ai_patrol_eigenflux_advi | def feed_to_brain | 函数 | conn, suggestion_uid, expert_n | 高价值建议投喂 AI 脑库 |
| ai_patrol_eigenflux_advi | def send_to_eigenflux_messag | 函数 | conn, expert_name, expert_doma | 将咨询请求和专家建议写入 EigenFlux 消息表 |
| ai_patrol_eigenflux_advi | def run_advisor_round | 函数 | round_no | 单轮巡检-EigenFlux 顾问执行 |
| ai_patrol_eigenflux_advi | def main | 函数 |  |  |
| andromeda_auto_evolution | def trigger_evolution | 函数 | reason | 触发演化 daemon 提前跑一轮.
带冷却 (min_interval=30s |
| andromeda_auto_evolution | def reset_evolution_event | 函数 |  | 演化 daemon 跑完一轮后调这个清掉唤醒信号. |
| andromeda_auto_evolution | def _detect_ollama_host | 函数 |  | 每次调用都重新检测 Ollama 可用端口 (11434 CLI / 11435 |
| andromeda_auto_evolution | def _detect_machine_tier | 函数 |  | 检测当前机器档位: 'dev' (开发机 MacBook Pro) | 'lig |
| andromeda_auto_evolution | def _ollama_list_models | 函数 |  | 调用 Ollama API 获取已装模型名集合。
失败返回空集合（安全降级）。 |
| andromeda_auto_evolution | def _pick_best_derive_model | 函数 |  | 智能择优:
  dev 档  → 优先 14b → 13b → 12b → 7b |
| andromeda_auto_evolution | def _load_checkpoint | 函数 |  | 加载 checkpoint (不存在则返回 DEFAULTS) |
| andromeda_auto_evolution | def _save_checkpoint | 函数 | cp | 保存 checkpoint (原子写) |
| andromeda_auto_evolution | def _ollama_embed | 函数 | text | Ollama embedding — nomic-embed-text |
| andromeda_auto_evolution | def _ollama_chat | 函数 | prompt, system | Ollama chat — 开发机优先 14b, 失败自动降级 7b, 再失败走 |
| andromeda_auto_evolution | def _get_conn | 函数 |  | DB 连接 (WAL + timeout) |
| andromeda_auto_evolution | def _cosine | 函数 | a, b | numpy 加速余弦相似度 |
| andromeda_auto_evolution | def eigenflux_ingest | 函数 | cp | 从 EigenFlux 消息表抓新消息 → 写 ai_brain_enhance |
| andromeda_auto_evolution | def auto_detect | 函数 | cp | 增量扫描 ai_brain_enhanced_knowledge 中 creat |
| andromeda_auto_evolution | def auto_retrieve | 函数 | new_items, cp | 对新行做 Ollama 向量化 → 写本地向量存储 → 语义检索已存在向量找关联 |
| andromeda_auto_evolution | def auto_associate | 函数 | associations, new_items | 把关联提案写入 knowledge_graph_relations + know |
| andromeda_auto_evolution | def auto_derive | 函数 | associations, new_items, cp | 对高相似度关联 (>= reinforce_threshold) 调 Ollam |
| andromeda_auto_evolution | def _employee_role_system | 函数 | employee_type | 根据 employee_type 生成角色 system prompt |
| andromeda_auto_evolution | def ai_employees_discuss_der | 函数 | limit_per_derived, max_derived | 🆕 Stage 4.5 — AI 员工讨论最新 DERIVED_KNOWLEDG |
| andromeda_auto_evolution | def auto_reinforce | 函数 | new_items, cp | 对被高频关联到的已有知识:
  - confidence_score += 0. |
| andromeda_auto_evolution | def auto_expand | 函数 | new_items, reinforced_count, c | 根据本轮演化结果，自动生成增强建议 (写入 ai_enhancement_sug |
| andromeda_auto_evolution | def auto_optimize | 函数 | cp, stats | - 写入 mt_ai_self_evolution_log (演化历史, 复用现 |
| andromeda_auto_evolution | def auto_discover_gaps | 函数 | min_nodes_per_subject, top_n | 扫描知识图谱, 找节点数 < min_nodes_per_subject 的稀疏 |
| andromeda_auto_evolution | def auto_expand_knowledge | 函数 | gaps, concepts_per_subject | 对每个稀疏学科, 用 Ollama 生成 N 个关联概念 + 描述,
写入 kn |
| andromeda_auto_evolution | def iceberg_broadcast_derive | 函数 | cycle_num, derived_count, asso | 把本轮演化产出 (衍生数/关联数/填补学科数) 打包成广播消息,
推给 N 个活 |
| andromeda_auto_evolution | def auto_meta_phase_advance | 函数 | cp, stats | 每轮判定是否满足 Phase 升级条件.
条件基于 checkpoint 累积统 |
| andromeda_auto_evolution | def _ensure_schemas | 函数 |  | [2026-10-10] 自动建表 + 补列 — 幂等, 每次 run_cycl |
| andromeda_auto_evolution | def run_cycle | 函数 |  | 执行完整十阶段自演化循环 (2026-10-05 扩展).
Stage 0: E |
| andromeda_auto_evolution | def bulk_ingest | 函数 | max_batches, batch_size, sleep | 全量批量摄入 EigenFlux 消息 → 脑库 → 向量化 → 联想 → KG |
| andromeda_auto_evolution | def bulk_status | 函数 |  | bulk 摄入进度 (从 checkpoint 推断) |
| andromeda_auto_evolution | def get_status | 函数 |  | 当前演化状态 (供 API 查询) |
| andromeda_auto_evolution | def run_single_stage | 函数 | stage | 手动触发单个阶段 (调试用) |
| andromeda_auto_loop.py | def _resolve_daemon_db | 函数 |  | 返回真正被 smart_mount 管理的、含 mt_daemon_regist |
| andromeda_auto_loop.py | def ollama_chat | 函数 | sys_p, user_p, timeout |  |
| andromeda_auto_loop.py | def run_self_loop | 函数 |  | 一轮完整自律循环 |
| andromeda_auto_loop.py | def _ensure_flow | 函数 |  | 确保自律循环自己有一个合法 flow_id — 直接 DB 操作, 不 fork |
| andromeda_auto_loop.py | def _parse_ts | 函数 | hb |  |
| andromeda_auto_loop.py | def _reg_key_col | 函数 | conn |  |
| andromeda_auto_loop.py | def _loop_daemon_health | 函数 |  | daemon 健康巡检 v4 (主管存活感知 + 只读 live 权威 + 审计 |
| andromeda_auto_loop.py | def _loop_rule_strengthen | 函数 |  | 规则弱约束词扫描 + 自动写回 |
| andromeda_auto_loop.py | def _loop_auto_implement | 函数 |  | 建议池自动实施: 取 APPROVED 且 routine 的建议,
用 Q5  |
| andromeda_auto_loop.py | def _loop_self_research | 函数 |  | 进程内调用 andromeda_research.run_research_cy |
| andromeda_auto_loop.py | def _loop_promote_derivative | 函数 |  | 把已通过的 routine 研究提案衍生为建议池工作项.

闭环: run_re |
| andromeda_auto_loop.py | def _skill_slug | 函数 | prop_id, category |  |
| andromeda_auto_loop.py | def _stale_skill_path_if_val | 函数 | prop_id, category | 崩溃恢复探测: 该提案受控名的 SKILL.md 若已落盘且 frontmatt |
| andromeda_auto_loop.py | def _loop_consume_derivative | 函数 |  | 节流消费 RESEARCH_DERIVE: 研究提案 → 本地 Ollama 生 |
| andromeda_auto_loop.py | def _loop_benchmark_if_neede | 函数 |  | 每 24h 跑一次模型 benchmark |
| andromeda_auto_loop.py | def _loop_hygiene_code | 函数 |  | 代码卫生 chunk（AST 屎山检测）。引擎内部按 60min 节流、跨 ti |
| andromeda_auto_loop.py | def _loop_hygiene_file | 函数 |  | 零散/未归类文件检测（项目根散落 + 目录职责错放 + 异常命名, 含 git  |
| andromeda_auto_loop.py | def _record_run | 函数 | dt, results | 记录到 mt_evolution_runs |
| andromeda_auto_loop.py | def log | 函数 | msg |  |
| andromeda_autopilot_v2.p | **class AutoPilotV2** | 类 | | Andromeda Autopilot V2 — 统一引擎接口

封装模块级 r |
| | ↳ def __init__ | 方法 | self, db_path |  |
| | ↳ def start | 方法 | self |  |
| | ↳ def stop | 方法 | self |  |
| | ↳ def run_loop_once | 方法 | self |  |
| | ↳ def run_loop | 方法 | self, interval |  |
| | ↳ def emit_event | 方法 | self, event_name, target, payl |  |
| | ↳ def health_check | 方法 | self |  |
| andromeda_autopilot_v2.p | def get_conn | 函数 |  |  |
| andromeda_autopilot_v2.p | def check_collector_health | 函数 |  |  |
| andromeda_autopilot_v2.p | def repair_collector | 函数 |  |  |
| andromeda_autopilot_v2.p | def check_learner_health | 函数 |  |  |
| andromeda_autopilot_v2.p | def repair_learner | 函数 |  |  |
| andromeda_autopilot_v2.p | def check_brain_health | 函数 |  |  |
| andromeda_autopilot_v2.p | def repair_brainfeed | 函数 |  |  |
| andromeda_autopilot_v2.p | def check_derivation_health | 函数 |  |  |
| andromeda_autopilot_v2.p | def repair_derivation | 函数 |  |  |
| andromeda_autopilot_v2.p | def check_collab_health | 函数 |  |  |
| andromeda_autopilot_v2.p | def repair_collab | 函数 |  |  |
| andromeda_autopilot_v2.p | def check_rebound_health | 函数 |  |  |
| andromeda_autopilot_v2.p | def invoke_rebound | 函数 |  |  |
| andromeda_autopilot_v2.p | def check_heal_health | 函数 |  |  |
| andromeda_autopilot_v2.p | def invoke_heal | 函数 |  |  |
| andromeda_autopilot_v2.p | def _aimeta_hook | 函数 | action, **kwargs | 🧠 AI Meta-Cognition Hook — 从 Autopilot 调 |
| andromeda_autopilot_v2.p | def run_heartbeat | 函数 |  |  |
| andromeda_autopilot_v2.p | def scan_new_engines | 函数 |  |  |
| andromeda_autopilot_v2.p | def proactive_patrol | 函数 |  |  |
| andromeda_autopilot_v2.p | def main | 函数 |  |  |
| andromeda_autopilot_v2.p | def S3_feed_trade | 函数 | payload | 单笔交易触发 → 写入 AI 脑库投喂 (fm_brain_feed)

Tri |
| andromeda_base.py | **class BaseAndromedaSubsystem** | 类 | | 所有仙女位子系统的公共基类 |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def _ensure_standard_columns | 方法 | self | 确保子系统表有 final_text/status/created_at/don |
| | ↳ def write_task | 方法 | self, task_id, raw_output, **e | 统一收口: 把 Ollama 输出 + 元数据落库 + 写 artifact.
 |
| | ↳ def _check_ollama | 方法 | self |  |
| | ↳ def ollama_generate | 方法 | self, prompt, model, temperatu | 本地 Ollama 推理 — 零 token 消耗 |
| | ↳ def save_artifact | 方法 | self, task_id, content, header | 写入 artifact 文件, 返回路径 |
| | ↳ def db_insert_task | 方法 | self, task_id, **kwargs | 往子系统 DB_TABLE 插入一条 task. kwargs 是 {col:  |
| | ↳ def db_update_task | 方法 | self, task_id, **kwargs |  |
| | ↳ def db_get_task | 方法 | self, task_id |  |
| | ↳ def db_list_tasks | 方法 | self, limit, where, args |  |
| | ↳ def register_daemon | 方法 | self, duty | 往 mt_daemon_registry 注册自己 |
| | ↳ def register_ai_employees | 方法 | self, employees | 批量注册 AI 员工分身 |
| | ↳ def new_task_id | 方法 | prefix |  |
| andromeda_base.py | def detect_ollama | 函数 | preferred_models | 返回 (port, best_model, all_models). 端口+模型 |
| andromeda_base.py | def register_all_subsystems | 函数 |  | 扫描 engines/ 下的 ai_*_engine.py, 找 BaseAnd |
| andromeda_bridge.py | def audio_open | 函数 | rate, bits, channels | 打开 I2S DMA 输出通道 |
| andromeda_bridge.py | def audio_write | 函数 | data | 写 PCM 数据到 ES8311 |
| andromeda_bridge.py | def audio_close | 函数 |  |  |
| andromeda_bridge.py | def set_volume | 函数 | vol | ES8311 音量控制 (I2C 写寄存器) |
| andromeda_bridge.py | def on_write | 函数 | char, data | 核心入口: 仙女座的 BLE 写入全部进来这里 |
| andromeda_bridge.py | def audio_beep | 函数 | freq, dur_ms, vol | 生成并播放蜂鸣声 (方波) |
| andromeda_bridge.py | def on_read | 函数 | char | 读请求 — 返回身份/状态 |
| andromeda_bridge.py | def ble_init | 函数 |  |  |
| andromeda_bridge.py | def main | 函数 |  |  |
| andromeda_cluster_matrix | def _detect_model | 函数 |  |  |
| andromeda_cluster_matrix | def _connect | 函数 |  |  |
| andromeda_cluster_matrix | def ensure_cluster_tables | 函数 |  |  |
| andromeda_cluster_matrix | def seed_cluster_nodes | 函数 |  |  |
| andromeda_cluster_matrix | async def _ollama_generate_aio | 函数 | session, prompt, sem, model, t | asyncio 并发 Ollama generate → 带 Semaphore |
| andromeda_cluster_matrix | def _build_prompt | 函数 | topic, dim_name, expert_name,  |  |
| andromeda_cluster_matrix | async def _single_dim_divergent | 函数 | session, sem, topic, dim_name, | 单节点单维度 → 并发调 Ollama + fallback 模板 |
| andromeda_cluster_matrix | async def execute_round_async | 函数 | topic | v3: asyncio 并发执行一轮 → 36 任务并发 Semaphore 限 |
| andromeda_cluster_matrix | def _pick_topic | 函数 | conn |  |
| andromeda_cluster_matrix | def status | 函数 |  |  |
| andromeda_cluster_matrix | def main | 函数 |  |  |
| andromeda_code_hygiene_e | def _is_excluded | 函数 | rel_posix |  |
| andromeda_code_hygiene_e | def list_code_files | 函数 | scope | 返回排序后的待扫 .py（相对 flask-app 的 POSIX 路径）。sc |
| andromeda_code_hygiene_e | def _now | 函数 |  |  |
| andromeda_code_hygiene_e | def _rel_project | 函数 | abs_path |  |
| andromeda_code_hygiene_e | def _conn | 函数 |  |  |
| andromeda_code_hygiene_e | def ensure_tables | 函数 |  |  |
| andromeda_code_hygiene_e | def _norm_tokens | 函数 | text, n |  |
| andromeda_code_hygiene_e | def _walk_skip_nested | 函数 | node | 遍历子树但不进入嵌套函数（保证函数指标归属正确）。 |
| andromeda_code_hygiene_e | def _cyclomatic | 函数 | fn |  |
| andromeda_code_hygiene_e | def _nest_depth | 函数 | node |  |
| andromeda_code_hygiene_e | def _arg_count | 函数 | fn |  |
| andromeda_code_hygiene_e | def _sev_rank | 函数 | s |  |
| andromeda_code_hygiene_e | def _mk | 函数 | rule_id, sev, rel, line, symbo |  |
| andromeda_code_hygiene_e | def analyze_code_file | 函数 | rel, abs_path, dup_index, dup_ | 分析单个 .py，返回 findings 列表；dup_index/dup_pa |
| andromeda_code_hygiene_e | def _git_tracked | 函数 |  |  |
| andromeda_code_hygiene_e | def scan_file_health | 函数 | tracked | 一轮文件卫生（轻量、全量），返回 findings 列表。 |
| andromeda_code_hygiene_e | def _fingerprint | 函数 | category, f |  |
| andromeda_code_hygiene_e | def upsert_findings | 函数 | findings, category, sweep_id | 幂等落库。返回 (new_open, still_open)。 |
| andromeda_code_hygiene_e | def close_stale | 函数 | sweep_id, category |  |
| andromeda_code_hygiene_e | def _get_state | 函数 | kind |  |
| andromeda_code_hygiene_e | def _set_state | 函数 | kind, phase, sweep_id, idx, to |  |
| andromeda_code_hygiene_e | def _last_done_ts | 函数 | kind |  |
| andromeda_code_hygiene_e | def _write_run | 函数 | run_id, kind, sweep_id, starte |  |
| andromeda_code_hygiene_e | def scan_code_chunk | 函数 | force_new | 跑一个代码扫描 chunk。返回结果 dict（phase=running/do |
| andromeda_code_hygiene_e | def scan_file_round | 函数 | force | 一轮文件卫生（轻量，到点才跑）。 |
| andromeda_code_hygiene_e | def _apply_fix | 函数 | abs_path, rule_id, line, symbo |  |
| andromeda_code_hygiene_e | def autofix_safe | 函数 | limit |  |
| andromeda_code_hygiene_e | def promote_high_to_pool | 函数 | per_loop |  |
| andromeda_code_hygiene_e | def _feed | 函数 | kind, content |  |
| andromeda_code_hygiene_e | def archive_legacy_sniff | 函数 |  | 把 auto_sniff_engine 历史 EVALUATED 噪音幂等归档为 |
| andromeda_code_hygiene_e | def loop_code_tick | 函数 |  |  |
| andromeda_code_hygiene_e | def loop_file_tick | 函数 |  |  |
| andromeda_code_hygiene_e | def status | 函数 |  |  |
| andromeda_code_hygiene_e | def _dry_run | 函数 | limit, scope |  |
| andromeda_code_hygiene_e | def main | 函数 |  |  |
| andromeda_compute_elasti | **class ComputeElasticityEngine** | 类 | | 算力弹性引擎 |
| | ↳ def __init__ | 方法 | self, db_path |  |
| | ↳ def ping_hulk | 方法 | self | 心跳 |
| | ↳ def decide | 方法 | self, task_type, batch_size | 决策: 这个任务该不该 offload 到 hulk? |
| | ↳ def offload_vector_prep | 方法 | self, rows | 把 auto_evolution Stage 1 批量向量化预处理 offloa |
| | ↳ def run_once | 方法 | self | daemon 工作体: 心跳 + 决策采样 |
| andromeda_compute_elasti | def _mini_cpu | 函数 |  | mini 当前 CPU % (从 top 1s 采样) |
| andromeda_compute_elasti | def _hulk_metrics | 函数 |  | SSH hulk 取 CPU/内存/负载 |
| andromeda_compute_elasti | def run_once | 函数 |  |  |
| andromeda_compute_elasti | def main | 函数 |  |  |
| andromeda_core.py | def ollama_chat | 函数 | model, system, user, timeout | 统一 Ollama chat API |
| andromeda_core.py | def ollama_embedding | 函数 | text |  |
| andromeda_core.py | def rag_search | 函数 | query, top_k | 本地 RAG 语义检索 (表名: local_vectors) |
| andromeda_core.py | def log | 函数 | msg, tag |  |
| andromeda_core.py | def _db_connect | 函数 | wal | 带 WAL + timeout 的 SQLite 连接, 解决多进程 lock  |
| andromeda_core.py | def _retry_exec | 函数 | conn, sql, params, max_retries | 带 retry 的 execute, 应对 database is locked |
| andromeda_core.py | def extract_func_code | 函数 | filepath, func_name, class_nam | 从 Python 文件精准提取目标函数/类方法的完整代码块.

Returns: |
| andromeda_core.py | def patch_func_code | 函数 | filepath, func_name, new_func_ | 把 new_func_code 精准 patch 到文件里替换原函数.
Retu |
| andromeda_core.py | def dev_activity_preflight | 函数 | flow_id, required_step | §14 MT_IR_D9 本地版前置拦截. 返回 True 才允许继续. |
| andromeda_core.py | def advance_flow | 函数 | flow_id, to_step | §14 MT_IR_D2 按边集合推进状态. 返回 True 成功. |
| andromeda_core.py | def auto_create_autofix_flow | 函数 | target, gap, scan_type | §12 IA-02: 每次 autofix 自动创建 flow_id 并直达 S |
| andromeda_core.py | def advisor_ask | 函数 | domain, question, max_advisors | 👥 向顾问团询价. 返回 [{"advisor_id":..., "name": |
| andromeda_core.py | def council_dispatch | 函数 | loop_name, task | 👥 派发天团执行. 返回 [exec_ids...]. 把任务分配给 mappe |
| andromeda_core.py | def rule_compliance_scan | 函数 | loop_name | 🌐 仙女座规则合规扫描 —— 每个 Loop 执行前调用.

Returns:
 |
| andromeda_core.py | def ensure_tables | 函数 |  |  |
| andromeda_core.py | def ollama_code | 函数 | system, user, timeout | 调用 coder:14b 生成代码 (比 chat 更适合写大段代码) |
| andromeda_core.py | def verify_code | 函数 | code, file_label | 仙女座自动验证: 写临时文件 → py_compile → 返回结果 |
| andromeda_core.py | def loop_self_architect | 函数 |  | 🏛️ 仙女座自己扫自己的架构 + 生成重构建议.
扫描: 自身代码 def/类/ |
| andromeda_core.py | def loop_evolve | 函数 |  |  |
| andromeda_core.py | def restart_daemon | 函数 | name | 真正重启一个 dead daemon → (ok, new_pid_or_err |
| andromeda_core.py | def loop_repair | 函数 |  |  |
| andromeda_core.py | def loop_patrol | 函数 |  |  |
| andromeda_core.py | def loop_rule | 函数 |  |  |
| andromeda_core.py | def loop_benchmark | 函数 |  |  |
| andromeda_core.py | def loop_awaken | 函数 |  |  |
| andromeda_core.py | def loop_feature_build | 函数 |  |  |
| andromeda_core.py | def loop_iceberg_opt | 函数 |  |  |
| andromeda_core.py | def loop_error_capture | 函数 |  |  |
| andromeda_core.py | def loop_auto_fix | 函数 |  |  |
| andromeda_core.py | def loop_sniff | 函数 |  |  |
| andromeda_core.py | def loop_brain_feed | 函数 |  |  |
| andromeda_core.py | def run_cycle | 函数 |  |  |
| andromeda_core.py | def run_loop | 函数 |  | 守护进程: 每 300s 一轮 |
| andromeda_core.py | def run_status | 函数 |  | 全局状态快照 |
| andromeda_core.py | def main | 函数 |  |  |
| andromeda_goal_engine.py | **class GoalEngine** | 类 | | 仙女座目标体系引擎 — 完整自洽 |
| | ↳ def __init__ | 方法 | self, db_path |  |
| | ↳ def seed | 方法 | self | 首次运行写入种子目标 (幂等) |
| | ↳ def run_once | 方法 | self | 单轮: 种子 → Q5 自省 → 更新进度 → 弱目标 hook |
| | ↳ def scan_weak_for_iceberg | 方法 | self | iceberg.pulse() 调用此函数 — 弱目标 → 触发 strengt |
| | ↳ def _count | 方法 | self, table |  |
| | ↳ def _iceberg_health | 方法 | self |  |
| andromeda_goal_engine.py | def _ollama | 函数 | system, user, timeout |  |
| andromeda_goal_engine.py | def _ollama_json | 函数 | system, user, timeout | 强制 JSON 输出 |
| andromeda_goal_engine.py | def run_once | 函数 |  |  |
| andromeda_goal_engine.py | def main | 函数 |  |  |
| andromeda_mcp_bridge.py | **class MCPHandler** | 类 | |  |
| | ↳ def log_message | 方法 | self, f, *a |  |
| | ↳ def _send | 方法 | self, obj, code, headers |  |
| | ↳ def _rpc_ok | 方法 | self, rpc_id, result |  |
| | ↳ def _rpc_err | 方法 | self, rpc_id, code, msg |  |
| | ↳ def do_OPTIONS | 方法 | self |  |
| | ↳ def do_GET | 方法 | self |  |
| | ↳ def do_POST | 方法 | self |  |
| | ↳ def _handle_tool_call | 方法 | self, rpc_id, params |  |
| andromeda_mcp_bridge.py | def _grace | 函数 | s, f |  |
| andromeda_mcp_bridge.py | def _log | 函数 | msg |  |
| andromeda_mcp_bridge.py | def _stats_inc | 函数 | tool_name, is_marvis, error |  |
| andromeda_mcp_bridge.py | def _flask_call | 函数 | path, method, data | 调本地 Flask API (SERVER 模式, 无 CSRF 拦截) |
| andromeda_mcp_bridge.py | def _marvis_mcp_call | 函数 | method, params, rpc_id | 代理调用 Marvis Editor SDK MCP (Auth disable |
| andromeda_mcp_bridge.py | def _launchctl_run | 函数 | *args |  |
| andromeda_mcp_bridge.py | def tool_diagnose_system | 函数 | **kw | 一键诊断 Mac mini 系统健康 (daemon + Flask + 握手  |
| andromeda_mcp_bridge.py | def tool_heal_system | 函数 | **kw | 一键自愈 — 重启崩溃 daemon + 触发握手重连 + 清磁盘 |
| andromeda_mcp_bridge.py | def tool_restart_daemon | 函数 | target, **kw | 重启指定 daemon. target: cloudflared|flask|a |
| andromeda_mcp_bridge.py | def tool_handshake_status | 函数 | **kw | 仙女座 EigenFlux 握手状态 (Mac mini ↔ MacBook P |
| andromeda_mcp_bridge.py | def tool_vikey_check | 函数 | **kw | VIKEY USB + Touch ID 双密钥在线状态 |
| andromeda_mcp_bridge.py | def tool_flask_health | 函数 | **kw | Flask :8888 健康检查 |
| andromeda_mcp_bridge.py | def tool_db_stats | 函数 | **kw | SQLite DB 表数 / Top15 行数 / 大小 |
| andromeda_mcp_bridge.py | def tool_list_users | 函数 | **kw | 用户列表 + 角色 + 启用状态 |
| andromeda_mcp_bridge.py | def tool_disk_check | 函数 | **kw | 磁盘空间 + inode |
| andromeda_mcp_bridge.py | def tool_list_daemons | 函数 | **kw | launchctl mtscos 系列 daemon 状态 (PID + exi |
| andromeda_mcp_bridge.py | def tool_exec_shell | 函数 | cmd, **kw | 执行受限 shell 命令 (运维只读, 零代码执行风险). 禁 python3 |
| andromeda_mcp_bridge.py | def tool_marvis_proxy | 函数 | sdk_tool, arguments, **kw | 调用 Marvis Editor SDK 原始 MCP tool (slide/ |
| andromeda_mcp_bridge.py | def _ai_analyze | 函数 | diagnosis_list, summary | 规则引擎 v2 — 结构化诊断项精确匹配, 杜绝误报 |
| andromeda_mcp_bridge.py | def tool_ai_diagnose | 函数 | **kw | 🧠 AI 根因分析 — diagnose_system 结果喂规则引擎, 输出根 |
| andromeda_mcp_bridge.py | def tool_cross_tunnel_health | 函数 | **kw | 🌐 跨设备通道健康检测 — Tailscale 优先 (零配置), Cloudf |
| andromeda_mcp_bridge.py | def tool_system_metrics | 函数 | **kw | 📡 实时系统指标 — CPU/内存/磁盘/daemon 状态/网络, 可作为 M |
| andromeda_mcp_bridge.py | def _check_mcp_preflight | 函数 | tool_name, arguments | §14 MT_IR_D9: MCP Hub tool 调用前置检查 → (all |
| andromeda_mcp_bridge.py | def _audit_db | 函数 |  | 连接审计库 (Flask 主库 app.db), 确保 3 张自主强化表存在 |
| andromeda_mcp_bridge.py | def tool_git_snapshot | 函数 | tag, **kw | 🛡️ L0 安全栅栏 — git commit 快照当前项目状态, 任何操作前先 |
| andromeda_mcp_bridge.py | def tool_patrol_rounds | 函数 | rounds, interval_sec, **kw | 🔄 L0 全链路定时巡检 — 跑 diagnose_system + ai_di |
| andromeda_mcp_bridge.py | def tool_ai_propose_upgrade | 函数 | focus, **kw | 🚀 L1 AI 提案 — 本地规则引擎审查当前代码状态 + 生成改进提案, 存  |
| andromeda_mcp_bridge.py | def tool_auto_apply_patch | 函数 | target, daemon, **kw | ⚡ L2 自主修复 — 仅限预批准白名单: restart_daemon(白名单 |
| andromeda_mcp_bridge.py | def _load_marvis_tools | 函数 |  | 从 Marvis Editor SDK 动态拉 tools/list, 加 ma |
| andromeda_mcp_bridge.py | def _register_v22_tools | 函数 |  | v2.2.0 自主强化 4 个 tool — 在函数定义后再注册到 HANDLE |
| andromeda_mcp_bridge.py | def _is_marvis_tool | 函数 | name |  |
| andromeda_meta_cognition | **class MetaCognitionEngine** | 类 | | 元认知引擎 — 知道自己知道什么/不知道什么 |
| | ↳ def __init__ | 方法 | self, db_path |  |
| | ↳ def introspect | 方法 | self, health_score, brain_now, | iceberg.pulse() 每轮调用 — 做一次快速自省 |
| | ↳ def register_uncertainty | 方法 | self, task_desc, confidence_lo | 被 auto_evolution / research 等模块调用 — 登记低置 |
| | ↳ def run_once | 方法 | self | 独立 daemon 工作体 — 批量 introspection + 清理过期 |
| andromeda_meta_cognition | def _ollama | 函数 | system, user, timeout |  |
| andromeda_meta_cognition | def _ollama_json | 函数 | system, user, timeout |  |
| andromeda_meta_cognition | def run_once | 函数 |  |  |
| andromeda_meta_cognition | def main | 函数 |  |  |
| andromeda_notifier.py | def notify | 函数 | title, content, level, daemon | 仙女座统一后台通知 (三通道自动全开)

Args:
    title:    |
| andromeda_notifier.py | def notify_evolution | 函数 | trigger_type, reason, source | 演化引擎通知 |
| andromeda_notifier.py | def notify_web_learner | 函数 | brain_add, category_detail | 互联网学习通知 |
| andromeda_notifier.py | def notify_troupe | 函数 | produced, writers_count | 文学天团通知 |
| andromeda_notifier.py | def notify_rule_enforcer | 函数 | rule_name, action, detail | 规则执行通知 |
| andromeda_notifier.py | def notify_autosync | 函数 | host, status, detail | autosync mini 状态通知 |
| andromeda_notifier.py | def notify_darwin | 函数 | debate_topic, winner | 达尔文辩论通知 |
| andromeda_notifier.py | def notify_video_pipeline | 函数 | scenes_count, duration, writer | 短视频 pipeline 通知 |
| andromeda_prompt_learnin | def phase3_ingest | 函数 |  |  |
| andromeda_prompt_learnin | def phase4_adapt | 函数 |  |  |
| andromeda_prompt_learnin | def phase5_feed | 函数 | int_kp, int_sk, int_np, iceber |  |
| andromeda_research.py | def ollama | 函数 | sys_p, user_p, timeout |  |
| andromeda_research.py | def _ensure_tables | 函数 | db | 研究提案 + 实施记录表 |
| andromeda_research.py | def brainstorm_new_features | 函数 | db, n | 让 Q5 基于系统现状想 n 个值得做的新功能 |
| andromeda_research.py | def classify_sensitivity | 函数 | title, summary | 敏感度分类 (routine/sensitive/major) |
| andromeda_research.py | def eigenflux_vote | 函数 | title, summary, sensitivity | EigenFlux 专家投票 |
| andromeda_research.py | def auto_implement | 函数 | proposal, flow_id | routine 提案自动实施 — Q5 生成代码 patch 并写入文件 |
| andromeda_research.py | def run_research_cycle | 函数 | max_proposals | 一轮研究循环 |
| andromeda_research.py | def _load_ir14 | 函数 |  | 加载 mt_ir14_dev_flow 并把它的 APP_DB 重定向到研究/演 |
| andromeda_research.py | def close_research_proposal | 函数 | prop_id, artifact, db | 把一个 routine 研究提案的 §14 flow 沿官方合法边走到 FINA |
| andromeda_research.py | def close_deployed_research_ | 函数 | limit | 一次性收口历史孤儿 flow: 仅关已有 DEPLOYED 衍生产物、仍 OPE |
| andromeda_research.py | def log | 函数 | msg |  |
| andromeda_self_heal.py | def _graceful_exit | 函数 | signum, frame |  |
| andromeda_self_heal.py | def _db | 函数 |  |  |
| andromeda_self_heal.py | def _log_anomaly | 函数 | anomaly_type, severity, descri | 上报异常到特征库 — 匹配已有条目则 frequency++, 否则新建 |
| andromeda_self_heal.py | def _log_heartbeat | 函数 | flask_alive, flask_http_200, d |  |
| andromeda_self_heal.py | def _log_uptime_event | 函数 | pid, event, reason, alive_seco | 记录 Flask 启动/退出 |
| andromeda_self_heal.py | def check_flask_pid | 函数 |  | Flask PID 文件里的进程还活着? |
| andromeda_self_heal.py | def check_flask_http | 函数 |  | HTTP /index 200? |
| andromeda_self_heal.py | def check_port_listening | 函数 |  |  |
| andromeda_self_heal.py | def check_db_writable | 函数 |  |  |
| andromeda_self_heal.py | def _run_fix_script | 函数 | script, label |  |
| andromeda_self_heal.py | def _kill_old_flasks | 函数 |  | 杀所有 8888 上的进程 |
| andromeda_self_heal.py | def _clean_port | 函数 |  | 确保端口空 |
| andromeda_self_heal.py | def _clear_pycache | 函数 |  |  |
| andromeda_self_heal.py | def _start_flask | 函数 |  | 启动 Flask, 返回 PID 或 None |
| andromeda_self_heal.py | def _mcp_call | 函数 | tool_name, arguments, timeout | 调仙女座 MCP Hub tool — 返回 (ok, result_dict_ |
| andromeda_self_heal.py | def _try_mcp_heal | 函数 |  | v2.0.0: 优先用 MCP heal_system 统一自愈. 返回 (us |
| andromeda_self_heal.py | def attempt_recovery | 函数 |  | 匹配特征库 → 执行修复 (v2.0.0: 优先 MCP heal_system |
| andromeda_self_heal.py | def main | 函数 |  |  |
| andromeda_society_engine | def _connect | 函数 |  |  |
| andromeda_society_engine | def _now | 函数 |  |  |
| andromeda_society_engine | def _due | 函数 | module |  |
| andromeda_society_engine | def _mark | 函数 | module |  |
| andromeda_society_engine | def _feed | 函数 | conn, fed_by, target, preview | 统一留痕: 脑库投喂 (全系统审计通道). |
| andromeda_society_engine | def survey_once | 函数 | conn, _retries |  |
| andromeda_society_engine | def _survey_inner | 函数 | conn |  |
| andromeda_society_engine | def mentorship_once | 函数 | conn, _retries |  |
| andromeda_society_engine | def _mentor_inner | 函数 | conn |  |
| andromeda_society_engine | def rotation_once | 函数 | conn, _retries |  |
| andromeda_society_engine | def _rotation_inner | 函数 | conn |  |
| andromeda_society_engine | def incubate_once | 函数 | conn, _retries |  |
| andromeda_society_engine | def _incubate_inner | 函数 | conn |  |
| andromeda_society_engine | def legislature_once | 函数 | conn, _retries |  |
| andromeda_society_engine | def _legis_inner | 函数 | conn |  |
| andromeda_society_engine | def strategy_once | 函数 | conn, _retries |  |
| andromeda_society_engine | def _strategy_inner | 函数 | conn |  |
| andromeda_society_engine | def org_review_once | 函数 | conn, _retries |  |
| andromeda_society_engine | def _org_inner | 函数 | conn |  |
| andromeda_society_engine | def _heartbeat | 函数 |  | Flow unified_ops 20261023: 改走 Flask /api |
| andromeda_society_engine | def main | 函数 |  |  |
| andromeda_status_page.py | def _get_mini_sync | 函数 |  | SSH 拉 mini DB 关键表 count + 最近时间戳, 返回 list |
| andromeda_status_page.py | def db | 函数 |  |  |
| andromeda_status_page.py | def _fmt_ts | 函数 | ts | 把各种 timestamp (Unix float / ISO str / No |
| andromeda_status_page.py | def _check_mini | 函数 |  | 检测 mini 在线状态 + SSH uptime/load, 返回 dict |
| andromeda_status_page.py | def get_data | 函数 |  | 一次性返回所有状态数据 (前端 2.5s 轮询) |
| andromeda_status_page.py | def api_sync_refresh | 函数 |  | 清缓存 + 重新拉 mini_sync |
| andromeda_status_page.py | def api_sync_push | 函数 |  | 真正的双向同步: upsert, 两边取并集 |
| andromeda_status_page.py | def api_employees | 函数 |  |  |
| andromeda_status_page.py | def status_page | 函数 |  |  |
| andromeda_status_page.py | def root | 函数 |  |  |
| andromeda_status_page.py | def run | 函数 | host, port |  |
| andromeda_upgrade.py | def dry_run | 函数 |  | 输出升级报告 |
| andromeda_upgrade.py | def apply_upgrade | 函数 |  | 应用升级 — 给 goal_engine/meta_cognition/iceb |
| andromeda_upgrade.py | def verify_upgrade | 函数 |  | 升级后验证 |
| andromeda_warden.py | def _save_state | 函数 |  |  |
| andromeda_warden.py | def _load_state | 函数 |  |  |
| andromeda_warden.py | def _scan_resources | 函数 |  |  |
| andromeda_warden.py | def _scan_port | 函数 | port, health_url | 扫描端口 + 可选 HTTP health |
| andromeda_warden.py | def _scan_launchd | 函数 | subsys | 扫描 launchd 进程 + DB 数据新鲜度 |
| andromeda_warden.py | def _scan_process | 函数 | subsys |  |
| andromeda_warden.py | def _record_failure | 函数 | key, reason |  |
| andromeda_warden.py | def _should_heal | 函数 | key | 窗口内连续 ≥N 次失败 + 冷却已过 → 可以自愈 |
| andromeda_warden.py | def _heal | 函数 | subsys, scan_result | AI 接管: 按 tier 执行自愈 |
| andromeda_warden.py | def _record_health | 函数 | key, ok |  |
| andromeda_warden.py | def scan_all | 函数 |  | 扫描所有子系统 + 资源层 + 触发自愈 |
| andromeda_warden.py | def health_endpoint | 函数 |  | 供 Flask /api/sandbox/warden/status 调用 |
| andromeda_warden.py | def run | 函数 |  | 主守护循环 |
| andromeda_workflow_engin | def _ensure_tables | 函数 |  | 首次启动确保工作流表存在 (幂等 CREATE TABLE IF NOT EXI |
| andromeda_workflow_engin | def _register | 函数 | wf_id, name, stages, input_sch |  |
| andromeda_workflow_engin | def list_workflows | 函数 |  | 返回全部可用工作流清单 (公开元数据, 不含引擎内部实现). |
| andromeda_workflow_engin | def get_workflow | 函数 | wf_id |  |
| andromeda_workflow_engin | def run_workflow | 函数 | wf_id, input_data, trigger_sou | 执行一个工作流 — 持久化运行日志 + 计费.

blocking=True   |
| andromeda_workflow_engin | def _dispatch | 函数 | wf_id, input_data, stages | 根据 wf_id 分发给具体引擎. 每个 stage 写 stages 列表. |
| andromeda_workflow_engin | def _knowledge_ingest | 函数 | input_data, stages |  |
| andromeda_workflow_engin | def _hire_employee | 函数 | input_data, stages | 桥接 → hire → invite 全流程 (线程内同步跑, 依赖 ai_au |
| andromeda_workflow_engin | def _evolution_full_cycle | 函数 | input_data |  |
| andromeda_workflow_engin | def _code_hygiene | 函数 | input_data, stages |  |
| andromeda_workflow_engin | def _translate_batch | 函数 | input_data, stages |  |
| andromeda_workflow_engin | def _estimate_revenue | 函数 | wf_id, input_data, output | 按 pricing 表 + 实际量估算 revenue_usd. |
| andromeda_workflow_engin | def list_runs | 函数 | workflow_id, status, limit |  |
| andromeda_workflow_engin | def get_run | 函数 | run_id |  |
| andromeda_workflow_engin | def dashboard_summary | 函数 |  | 工作流 Dashboard: 今日运行数 / 总 revenue / 总 cos |
| collab_bus_engine.py | **class CollabBus** | 类 | | 协作总线核心: 线程安全的 Pub/Sub 单例

设计:
- 订阅者 = (i |
| | ↳ def __new__ | 方法 | cls |  |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def subscribe | 方法 | self, subscriber_id, subscribe | 注册订阅者
subscribe_events: ["MARKET_ANOMALY |
| | ↳ def unsubscribe | 方法 | self, subscriber_id |  |
| | ↳ def list_subscribers | 方法 | self |  |
| | ↳ def publish | 方法 | self, event_type, source, payl | 发布事件到总线
返回: {"event_id": str, "subscribe |
| | ↳ def get_status | 方法 | self |  |
| collab_bus_engine.py | **class MarketRadarDaemon** | 类 | | 市场雷达: 每 5s poll 新浪行情 → 异动检测 → 广播 |
| | ↳ def __new__ | 方法 | cls |  |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def start | 方法 | self, cycle |  |
| | ↳ def stop | 方法 | self |  |
| | ↳ def _run_loop | 方法 | self |  |
| | ↳ def _poll_and_broadcast | 方法 | self | 拉取新浪行情 → 异动检测 → 广播 |
| | ↳ def _detect_anomaly | 方法 | self, price, prev_close, chang | 异动检测 → (anomaly_type, anomaly_score 0-10 |
| | ↳ def _tick_count_increment | 方法 | self | 每 10 个 tick 返回 True (降频广播 MARKET_TICK) |
| | ↳ def get_cache | 方法 | self | 获取当前缓存 |
| collab_bus_engine.py | def _conn | 函数 |  |  |
| collab_bus_engine.py | def _now_iso | 函数 |  |  |
| collab_bus_engine.py | def _gen_id | 函数 | prefix |  |
| collab_bus_engine.py | def ensure_bus_tables | 函数 |  |  |
| collab_bus_engine.py | def get_collab_bus | 函数 |  | 获取协作总线单例 |
| collab_bus_engine.py | def register_standard_subscr | 函数 |  | 注册 5 个内置订阅者 (避免循环导入问题, 用延迟 import) |
| collab_bus_engine.py | def get_recent_events | 函数 | limit, event_type | 获取最近事件 |
| collab_bus_engine.py | def get_radar_cache | 函数 |  | 获取市场雷达缓存 |
| collab_bus_engine.py | def record_dispatch | 函数 | payload | 触发器分发记录 — 由 TriggerCoordinator 的 log han |
| collab_solidarity_engine | **class CollabSolidarityEngine** | 类 | | 🤝 协作团结引擎 — 把 33 个孤立中心连接成协作网络。 |
| | ↳ def __init__ | 方法 | self, db_path |  |
| | ↳ def rebuild_full_collab_matr | 方法 | self, causal_window_sec, min_e | 从 evolution_log 扫描"事件-中心"序列, 检测 5 秒内的因果协 |
| | ↳ def ai_suggest_collab_pairs | 方法 | self | 找出 collab_matrix 里还没出现过的孤立中心, 推理它们应该跟谁协作 |
| | ↳ def ai_broadcast_hub_network | 方法 | self | 当前: broadcast 是唯一 target (258 入度)
应该: 每个 |
| | ↳ def form_collab_pact | 方法 | self, center_a, center_b, pact | 签署协作契约。pact_type: PEER/DEPENDS_ON/PROVID |
| | ↳ def _pact_promise | 方法 | pact_type, self_name, other_na |  |
| | ↳ def run_solidarity_cycle | 方法 | self, auto_pact_count | 一键协作团结: rebuild → suggest → hub → pacts |
| | ↳ def close | 方法 | self |  |
| collab_solidarity_engine | def _db_conn | 函数 | readonly | 获取 DB 连接，支持只读 URI 模式。 |
| collab_solidarity_engine | def _ensure_tables | 函数 | conn | 首次运行自动建表。 |
| collab_solidarity_engine | def _now_iso | 函数 |  |  |
| collab_solidarity_engine | def _emit_trigger_event | 函数 | event_type, payload | 向 TriggerCoordinator 发射事件 (写入 mt_collab_ |
| collab_solidarity_engine | def _ollama_infer | 函数 | prompt, system, temperature, m | 调用 Ollama 本地模型推理，失败返回 None。 |
| collab_solidarity_engine | def main | 函数 |  |  |
| eigenflux_auto_vote.py | def ollama_chat | 函数 | system, user, timeout |  |
| eigenflux_auto_vote.py | def simulate_vote | 函数 | proposal, sensitivity, max_exp | 让 Q5 模拟 EigenFlux 专家投票。
proposal: 提案标题 + |
| eigenflux_auto_vote.py | def main | 函数 |  |  |
| eigenflux_broadcast_engi | **class BroadcastEvent** | 类 | | 广播事件 |
| eigenflux_broadcast_engi | **class ExpertInvitation** | 类 | | 专家邀请 |
| eigenflux_broadcast_engi | **class ChatSession** | 类 | | 聊天会话 |
| eigenflux_broadcast_engi | **class LearningUpgrade** | 类 | | 学习升级记录 |
| eigenflux_broadcast_engi | **class AnomalyFeedRecord** | 类 | | 异常投喂记录 |
| eigenflux_broadcast_engi | **class BroadcastReport** | 类 | | 广播引擎报告 |
| eigenflux_broadcast_engi | **class BroadcastCommunicator** | 类 | | AI员工与EigenFlux广播网络深度交流 |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def _log | 方法 | self, event, detail |  |
| | ↳ def broadcast | 方法 | self, sender_id, sender_name,  | 发起广播 — VII代主动试探版: 优先广播真实系统需求(巡检/建议池/异常), |
| | ↳ def probe_activity_ratio | 方法 | self | 主动试探占比 (VII代主动度指标): 真实需求广播/总广播 |
| | ↳ def _pick_real_demand | 方法 | self | 从真实需求源(巡检/建议池/异常投喂)提取试探主题 (主动试探核心) |
| | ↳ def _get_random_employees | 方法 | self, count | 从数据库获取随机员工 |
| | ↳ def get_broadcasts | 方法 | self |  |
| eigenflux_broadcast_engi | **class ExpertInviter** | 类 | | 自动邀请EigenFlux网络专家加入 |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def _log | 方法 | self, event, detail |  |
| | ↳ def invite_experts | 方法 | self, skill_gaps, max_invites | 邀请专家加入 |
| | ↳ def get_invitations | 方法 | self |  |
| eigenflux_broadcast_engi | **class FriendChatInitiator** | 类 | | AI员工主动发起好友聊天 |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def _log | 方法 | self, event, detail |  |
| | ↳ def initiate_chat | 方法 | self, employees | 发起好友聊天 |
| | ↳ def _generate_message | 方法 | self, topic, sender, msg_idx | 生成聊天消息 |
| | ↳ def _extract_tags | 方法 | self, content | 提取知识标签 |
| | ↳ def _get_random_employees | 方法 | self, count | 获取随机员工 |
| | ↳ def get_chat_sessions | 方法 | self |  |
| eigenflux_broadcast_engi | **class SmartLearningUpgrader** | 类 | | 智能自动升级AI员工学识/技能/能力 |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def _log | 方法 | self, event, detail |  |
| | ↳ def upgrade_learning | 方法 | self, employee | 执行学习升级 |
| | ↳ def _get_random_employee | 方法 | self | 获取随机员工 |
| | ↳ def _update_employee_accurac | 方法 | self, emp_id, new_accuracy | 更新员工准确率 |
| | ↳ def get_upgrades | 方法 | self |  |
| eigenflux_broadcast_engi | **class AnomalyAIFeeder** | 类 | | 自动检测AI异常行为并投喂脑库 |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def _log | 方法 | self, event, detail |  |
| | ↳ def detect_and_feed | 方法 | self, employee | 检测异常并投喂 |
| | ↳ def _get_anomaly_employee | 方法 | self | 获取可能异常的员工 |
| | ↳ def get_feeds | 方法 | self |  |
| eigenflux_broadcast_engi | **class EigenFluxBroadcastEngine** | 类 | | EigenFlux广播网络深度交流引擎 |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def _log | 方法 | self, event, detail |  |
| | ↳ def run_cycle | 方法 | self, flow_id, rounds | 执行单次交流周期 |
| | ↳ def _generate_report | 方法 | self, flow_id, broadcasts, inv | 生成报告 |
| | ↳ def _broadcast_to_dict | 方法 | self, b |  |
| | ↳ def _invitation_to_dict | 方法 | self, i |  |
| | ↳ def _chat_to_dict | 方法 | self, c |  |
| | ↳ def _upgrade_to_dict | 方法 | self, u |  |
| | ↳ def _feed_to_dict | 方法 | self, f |  |
| | ↳ def _persist_to_database | 方法 | self, flow_id, report | 持久化到数据库 |
| | ↳ def start_daemon | 方法 | self | 启动守护线程 |
| | ↳ def stop_daemon | 方法 | self | 停止守护线程 |
| | ↳ def _daemon_wrapper | 方法 | self, name, func, interval | 守护线程包装器 |
| | ↳ def _broadcast_loop | 方法 | self | 广播循环 |
| | ↳ def _invite_loop | 方法 | self | 邀请循环 |
| eigenflux_broadcast_engi | def _query_main_db | 函数 | sql, params, max_rows | 只读查询主库真实数据源 (巡检问题/建议池), 失败返回空列表 (绝不抛出) |
| eigenflux_broadcast_engi | def probe_topic_wellformed | 函数 | topic | 试探主题格式校验 (纯函数): 非空/长度>=8/无占位符词 |
| eigenflux_broadcast_engi | def broadcast_quality_score | 函数 | content, topic | 广播内容质量评分 (纯函数) 0.0-1.0: 长度分40%+具体性分30%+主 |
| eigenflux_broadcast_engi | def topic_keywords_of | 函数 | topic | 主题关键词切分 (纯函数): 按常见分隔符切词, 保留长度>=2的词, 最多6个 |
| eigenflux_broadcast_engi | def select_targets_by_match | 函数 | employees, topic, max_targets | 按主题-专长匹配度选择广播目标 (纯函数, 无DB): 匹配命中多的排前 |
| eigenflux_broadcast_engi | def probe_ratio_of | 函数 | real_count, total_count | 真实需求主题占比 (主动度指标, 纯函数): 0.0-1.0 |
| eigenflux_broadcast_engi | def offline_first | 函数 |  | 本地零token铁律 (纯函数): 恒返 OFFLINE_ONLY |
| eigenflux_broadcast_engi | def ensure_broadcast_tables | 函数 |  | 确保广播引擎相关表存在 |
| eigenflux_dynamic_invite | def match_experts | 函数 | activity_description, activity | 根据活动描述匹配最对口的专家 + AI 员工。

匹配优先级:
1. 默认路由的 |
| eigenflux_dynamic_invite | def _llm_enhance | 函数 | desc, current_types | Q5 语义匹配补充专家 |
| eigenflux_dynamic_invite | def build_invitation | 函数 | result | 把 match_experts 结果 → 可直接发给专家的邀请消息 |
| eigenflux_proactive_engi | **class ExpertProfile** | 类 | | 专家画像 |
| | ↳ def success_rate | 方法 | self |  |
| eigenflux_proactive_engi | **class InterventionEvent** | 类 | | 介入事件 |
| eigenflux_proactive_engi | **class DiscussionSession** | 类 | | 讨论会话 |
| eigenflux_proactive_engi | **class ExamResult** | 类 | | 考试结果 |
| eigenflux_proactive_engi | **class EigenFluxProactiveEngine** | 类 | | EigenFlux专家主动介入引擎 |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def _load_experts | 方法 | self | 从数据库加载所有AI专家/员工 |
| | ↳ def _infer_group | 方法 | self, specialty, desc | 推断专家所属领域 |
| | ↳ def _get_exam_domain | 方法 | self, expert | 获取专家的考试领域 |
| | ↳ def proactive_intervene | 方法 | self, issue_type, severity, ta | 能力1: 主动介入调剂 - 发现异常自动介入协调 |
| | ↳ def _match_domain_to_issue | 方法 | self, issue_type | 根据问题类型匹配领域 |
| | ↳ def _persist_intervention | 方法 | self, event | 持久化介入事件 |
| | ↳ def proactive_enhance_assist | 方法 | self, target_area | 能力2: 专员主动完善增强和帮扶 |
| | ↳ def _identify_weak_areas | 方法 | self | 识别系统薄弱区域 |
| | ↳ def self_upgrade_knowledge | 方法 | self, expert_name | 能力3: 主动升级自身AI学识及能力 |
| | ↳ def _update_expert_db | 方法 | self, expert | 更新专家数据库记录 |
| | ↳ def scheduled_upgrade_and_ex | 方法 | self | 能力4: 定时升级和考试复合 - 定期考试，不合格降级 |
| | ↳ def _conduct_exam | 方法 | self, expert | 对专家进行考试 |
| | ↳ def _persist_exam | 方法 | self, result | 持久化考试结果 |
| | ↳ def team_discussion_and_reve | 方法 | self, topic | 能力5: 主动组队讨论及反向投喂 |
| eigenflux_proactive_engi | def _query_main_db | 函数 | sql, params, max_rows | 只读查询主库真实数据源 (巡检问题/建议池), 失败返回空列表 (绝不抛出) |
| eigenflux_proactive_engi | def probe_signal_wellformed | 函数 | signal | 试探信号格式校验 (纯函数): 非空/长度>=8/无占位符 |
| eigenflux_proactive_engi | def proactivity_score | 函数 | active_actions, passive_action | 主动参与度评分 (纯函数): active/(active+passive),  |
| eigenflux_proactive_engi | def probe_action_plan | 函数 | signals, max_actions | 试探动作计划 (纯函数): 从系统信号映射为(动作类型,目标)计划, 保底固定试 |
| eigenflux_proactive_engi | def offline_first | 函数 |  | 本地零token铁律 (纯函数): 恒返 OFFLINE_ONLY |
| eigenflux_proactive_engi | def get_engine | 函数 |  | 获取引擎单例 |
| generate_andromeda_25.py | def generate_engine | 函数 | star | 生成一个引擎文件的完整 Python 源码 |
| generate_andromeda_25.py | def main | 函数 |  |  |
| proposal_collab_engine.p | def _now | 函数 |  |  |
| proposal_collab_engine.p | def _ensure_engines_path | 函数 |  |  |
| proposal_collab_engine.p | def _db | 函数 |  |  |
| proposal_collab_engine.p | def _conn | 函数 |  |  |
| proposal_collab_engine.p | def init_tables | 函数 | conn | 初始化协作引擎所有表 (幂等) |
| proposal_collab_engine.p | def analyze_proposal | 函数 | proposal_id, conn, verbose | 🧠 AI 智能分析提案 → 自动生成协作方案

分析维度:
1. amount  |
| proposal_collab_engine.p | def _assess_risk | 函数 | prop, conn | 动态风险评估 |
| proposal_collab_engine.p | def _assess_complexity | 函数 | prop, channel | 复杂度评估 0-1 |
| proposal_collab_engine.p | def _assess_urgency | 函数 | prop, conn | 紧急度评估 0-1 |
| proposal_collab_engine.p | def _recommend_role_mix | 函数 | tier, risk, complexity, urgenc | 🎭 动态角色组合推荐 + 权衡配比

配比逻辑:
- L1 MICRO: 个体  |
| proposal_collab_engine.p | def _match_ai_employees | 函数 | tier, channel, risk, conn | 匹配最合适的 AI 员工 (主责 + 辅助) |
| proposal_collab_engine.p | def _fetch_external_knowledg | 函数 | prop, channel, conn | 从 KnowledgeBridge/行情/合规 引擎拉外部知识 |
| proposal_collab_engine.p | def _generate_plan_summary | 函数 | prop, tier, roles, weights, le | 生成人类可读的方案摘要 |
| proposal_collab_engine.p | def _write_trace | 函数 | conn, plan_id, proposal_id, st | 写一条东亚流痕迹 |
| proposal_collab_engine.p | def _generate_minutes | 函数 | conn, plan_id, proposal_id, pr | 自动生成纪要 (Markdown) |
| proposal_collab_engine.p | def _role_action_map | 函数 | role |  |
| proposal_collab_engine.p | def _role_output_map | 函数 | role |  |
| proposal_collab_engine.p | def dispatch_proposal | 函数 | proposal_id, conn, verbose | 📋 派单 — 把协作方案分配给各角色执行
(当前阶段: 写痕迹 + 标记 DIS |
| proposal_collab_engine.p | def _update_growth | 函数 | conn, employee_id, tier | 从小我到大我 — 成长追踪 |
| proposal_collab_engine.p | def run_pending_proposals | 函数 | limit, conn, verbose | 批量处理 PENDING/APPROVED 但没协作方案的提案 |
| proposal_collab_engine.p | def trace_proposal | 函数 | proposal_id, conn | 查看协作痕迹 |
| proposal_collab_engine.p | def run_collab_daemon | 函数 | interval_sec | 协作守护循环 (默认 10min 一轮) |
| roundtable_orchestrator. | def _validate_payload | 函数 | text |  |
| roundtable_orchestrator. | def main | 函数 |  |  |
| test_andromeda_status_pa | **class TestDatabase** | 类 | | DB 完整性检查 — 状态页所有 SELECT 的表都应存在 |
| | ↳ def setUp | 方法 | self |  |
| | ↳ def tearDown | 方法 | self |  |
| | ↳ def test_ai_employees_has_da | 方法 | self | 精选专家 ai_employees 表有数据 |
| | ↳ def test_mt_andromeda_regist | 方法 | self | 注册中心大表 mt_andromeda_employee_registry 有  |
| | ↳ def test_mt_andromeda_schema | 方法 | self | 注册中心表有 employee_id / name / employee_typ |
| | ↳ def test_sync_tables_exist | 方法 | self | mini 同步对比用的 8 张表都存在 |
| | ↳ def test_mini_push_tables_ex | 方法 | self | 手动同步 (开发机→mini) 的 7 张表 |
| test_andromeda_status_pa | **class TestApiData** | 类 | | /api/data 正常返回 |
| | ↳ def setUp | 方法 | self |  |
| | ↳ def test_data_200 | 方法 | self |  |
| | ↳ def test_brain_total_positiv | 方法 | self |  |
| | ↳ def test_employee_total_33k | 方法 | self | 之前的 bug: 读 ai_employees 只有 239 |
| | ↳ def test_mini_sync_has_8_tab | 方法 | self |  |
| | ↳ def test_mini_sync_table_lab | 方法 | self | mini_sync 每表应有 label/local/mini/diff |
| test_andromeda_status_pa | **class TestApiEmployees** | 类 | | /api/employees 搜索分页 |
| | ↳ def setUp | 方法 | self |  |
| | ↳ def test_default_pagination | 方法 | self | 默认参数 page=1 limit=20 |
| | ↳ def test_search_by_name | 方法 | self | 搜 name='expert' — 应该有 33k+ 结果 |
| | ↳ def test_search_by_type | 方法 | self | 按 employee_type 搜 eigenflux_expert |
| | ↳ def test_search_no_match | 方法 | self | 搜不存在的关键词 → 0 结果 |
| | ↳ def test_limit_bounds | 方法 | self | limit 必须在 1-100 之间 |
| | ↳ def test_pagination_page | 方法 | self | 翻到第 2 页, rows 应该不同 |
| | ↳ def test_types_aggregation | 方法 | self | 类型聚合应该有 eigenflux_expert |
| | ↳ def test_row_structure | 方法 | self | 每行应有 employee_id / name / employee_type  |
| | ↳ def test_negative_page | 方法 | self | page=-1 应该被 clamp 到 1 |
| test_andromeda_status_pa | **class TestApiSyncRefresh** | 类 | | /api/sync/refresh 清缓存 |
| | ↳ def setUp | 方法 | self |  |
| | ↳ def test_refresh_200 | 方法 | self |  |
| test_andromeda_status_pa | **class TestApiSyncPush** | 类 | | /api/sync/push — mini 离线/在线 |
| | ↳ def setUp | 方法 | self |  |
| | ↳ def test_push_mini_offline_4 | 方法 | self | mini 离线 → 返回 400 |
| | ↳ def test_push_mini_online_su | 方法 | self | mock mini 在线 + mock subprocess → 返回 200 |
| test_andromeda_status_pa | **class TestHtmlPage** | 类 | | /andromeda 页面关键元素 |
| | ↳ def setUp | 方法 | self |  |
| | ↳ def test_page_200 | 方法 | self |  |
| | ↳ def test_page_has_kpi | 方法 | self |  |
| | ↳ def test_page_has_mini_bar | 方法 | self |  |
| | ↳ def test_page_has_sync_panel | 方法 | self |  |
| | ↳ def test_page_has_employee_c | 方法 | self | AI 员工注册中心 + 搜索框 |
| | ↳ def test_page_has_charts | 方法 | self |  |
| test_andromeda_status_pa | **class TestWatchdogProcess** | 类 | | 守护进程健康检查 (只检查状态, 不 kill) |
| | ↳ def test_watchdog_running | 方法 | self | watchdog_status_page.py 守护进程在跑 |
| | ↳ def test_status_page_port_88 | 方法 | self | 8889 端口有进程监听 |
| | ↳ def test_status_page_api_res | 方法 | self | API /api/data 2 秒内响应 |
| andromeda_dashboard_rout | def _ensure_andromeda_tables | 函数 |  | flow_pages_all_20261020: 知识脑库/贡献者人格/文案永久 |
| andromeda_dashboard_rout | def _conn | 函数 | read_only | 仙女座专属 DB 连接

v22.19.1 容灾: engines/app.db |
| andromeda_dashboard_rout | def _daemon_rows | 函数 | conn | schema 兼容读取 daemon 注册表

engines 库列: daem |
| andromeda_dashboard_rout | def _query | 函数 | sql, args |  |
| andromeda_dashboard_rout | def _count | 函数 | table |  |
| andromeda_dashboard_rout | def _live_daemons | 函数 |  | 从 ps aux 拿当前活的 daemon 名 |
| andromeda_dashboard_rout | def dashboard_page | 函数 |  | 仙女座仪表盘主页面 |
| andromeda_dashboard_rout | def api_daemon_status | 函数 |  |  |
| andromeda_dashboard_rout | def api_db_metrics | 函数 |  | 核心表行数 + 24h 增量 |
| andromeda_dashboard_rout | def api_system_health | 函数 |  | 一键健康检查 |
| andromeda_dashboard_rout | def api_twin_machine | 函数 |  | Mac mini 健康状态 (需 ssh andromeda) |
| andromeda_dashboard_rout | def api_iceberg_structure | 函数 |  | 冰山三层架构快照 |
| andromeda_dashboard_rout | def api_evolution_timeline | 函数 |  | 11 阶段冰山演化时间线 + 全版本

schema 兼容: engines 库 |
| andromeda_dashboard_rout | def api_upgrade_reports | 函数 |  | 最近 20 份 4h 升级报告 |
| andromeda_dashboard_rout | def api_upgrade_overviews | 函数 |  | 全部 7d 升级总览 |
| andromeda_dashboard_rout | def api_copy_archive | 函数 |  | 文案永久存档 (分页, 每页 20) |
| andromeda_dashboard_rout | def knowledge_brain_page | 函数 |  | 仙女座知识脑库前端页面 (极暗星空风) |
| andromeda_dashboard_rout | def iceberg_evolution_page | 函数 |  | 冰山演化时间线前端 — 水墨赤壁赋 文人风 |
| andromeda_dashboard_rout | def iceberg_center_page | 函数 |  | 🧊 冰山统一控制中心 — 三层动态厚度 + 知识脑库融合 + 导航 |
| andromeda_dashboard_rout | def collapse_theorem_page | 函数 |  | PRIME_COLLAPSE_THEOREM 质因数递归坍缩7 可视化 |
| andromeda_dashboard_rout | def eigenflux_council_page | 函数 |  | EigenFlux 专家团 + 天团矩阵 + AI 员工 |
| andromeda_dashboard_rout | def gray_center_page | 函数 |  | 灰度发布中心 (flow_secondary_pages_20261018: 主 |
| andromeda_dashboard_rout | def iceberg_meta_page | 函数 |  | 冰山元数据看板 (flow_secondary_pages_20261018:  |
| andromeda_dashboard_rout | def upgrade_board_page | 函数 |  | 升级报告仪表盘 |
| andromeda_dashboard_rout | def health_board_page | 函数 |  | 🩺 冰山健康度仪表盘 — 真实心跳 + 停摆标红 + 坍缩锚点 |
| andromeda_dashboard_rout | def persona_chat_page | 函数 |  | 💬 AI 人格实时聊天室 — 多人格同时讨论 |
| andromeda_dashboard_rout | def knowledge_graph_page | 函数 |  | 🕸️ D3.js 知识图谱 力导向图 |
| andromeda_dashboard_rout | def api_knowledge_graph_data | 函数 |  | 🕸️ 知识图谱数据 (flow_redblue_ui_20261018: 修复页 |
| andromeda_dashboard_rout | def _ollama_chat_model | 函数 |  | 小龙保活: 聊天模型自动探测 (qwen2.5:7b 不存在时降级 14b, 避 |
| andromeda_dashboard_rout | def api_persona_chat | 函数 |  | 💬 AI 人格聊天室 — Ollama qwen2.5:7b + 脑库RAG + |
| andromeda_dashboard_rout | def api_persona_chat_history | 函数 |  | 💬 persona_chat 会话历史回放 (flow_andromeda_ch |
| andromeda_dashboard_rout | def api_iceberg_health | 函数 |  | 真实健康度数据 — 心跳停摆标红 |
| andromeda_dashboard_rout | def api_eigenflux | 函数 |  | EigenFlux 专家团 + 真实 daemon |
| andromeda_dashboard_rout | def api_upgrade_board | 函数 |  | 升级报告数据 |
| andromeda_dashboard_rout | def api_iceberg_layer_stats | 函数 |  | 知识脑库按冰山三层聚合 — 前端动态厚度数据源
v25.2: 主数据源切换 ai |
| andromeda_dashboard_rout | def api_iol_summary | 函数 |  | IOL 实时面板数据 — mt_iceberg_optimization_log |
| andromeda_dashboard_rout | def api_andromeda_daemon_sta | 函数 |  | 守护进程状态 — PID / Ollama / daemon registry |
| andromeda_dashboard_rout | def api_knowledge_search | 函数 |  | 知识脑库搜索 API — 支持关键词/领域/难度/平台 过滤 |
| andromeda_dashboard_rout | def api_knowledge_semantic | 函数 |  | 脑库语义检索 API (flow_andromeda_iceberg_20261 |
| andromeda_dashboard_rout | def api_knowledge_personas | 函数 |  | 知识贡献者人格档案列表 |
| andromeda_dashboard_rout | def api_knowledge_stats | 函数 |  | 知识脑库统计概览 |
| andromeda_dashboard_rout | def api_knowledge_ask | 函数 |  | 向 AI 人格请教 — 人格模板 + Ollama qwen2.5:7b 生成 |
| andromeda_dashboard_rout | def wenquxing_page | 函数 |  | 📜 文曲星 — 仙女座文学域 AI 写作生成器 (冰山内嵌) |
| andromeda_dashboard_rout | def api_wqx_generate | 函数 |  | 📜 文曲星生文 API — 调 ai_wenquxing_engine
权限规则 |
| andromeda_dashboard_rout | def api_wqx_task | 函数 | task_id | 查询单个文曲星任务 |
| andromeda_dashboard_rout | def api_wqx_list | 函数 |  | 历史任务列表 |
| andromeda_dashboard_rout | def _get_wqx_modes | 函数 |  | 返回 7 种模式 + 网文/脚本 genre 列表 (给模板用) |
| andromeda_dashboard_rout | def _check_wqx_ollama | 函数 |  | 检查 Ollama 是否在线 |
| andromeda_dashboard_rout | def _load_25_stars | 函数 |  | 从 generate_andromeda_25.py 读 25 星域定义 (轻量 |
| andromeda_dashboard_rout | def _get_star_context | 函数 | star_code, genre | 根据星域 code 返回该域的写作 context (让文曲星适配该域文案风格) |
| andromeda_dashboard_rout | def _get_wqx_literary_team | 函数 |  | 文曲星文学 AI 天团 — 5 位 AI 员工 + 仙女座文学专家组 |
| andromeda_dashboard_rout | def _get_wqx_eigenflux_helpe | 函数 |  | EigenFlux 专家团队 — 辅助文曲星创作 (风格/合规/视角) |
| andromeda_dashboard_rout | def _get_wqx_stats | 函数 |  | 文曲星产出统计 (从 DB) |
| andromeda_hub_routes.py | def _q | 函数 | conn, sql, args |  |
| andromeda_hub_routes.py | def _hub_payload | 函数 |  |  |
| andromeda_hub_routes.py | def andromeda_hub_page | 函数 |  | 🪐 仙女座总枢纽 — 四层全景页 (flow_andromeda_p4_2026 |
| andromeda_hub_routes.py | def api_andromeda_hub | 函数 |  |  |
| andromeda_param_routes.p | def _engine | 函数 |  |  |
| andromeda_param_routes.p | def _is_sa | 函数 |  |  |
| andromeda_param_routes.p | def param_center_page | 函数 |  | ⚙️ 仙女座参数中心 — 统一参数体系面板 |
| andromeda_param_routes.p | def api_param_list | 函数 |  | 参数清单 ?domain=ai  (is_secret=1 值脱敏) |
| andromeda_param_routes.p | def api_param_stats | 函数 |  | 参数体系总览: 域分布/类型分布/健康度/最近巡检 |
| andromeda_param_routes.p | def api_param_changelog | 函数 |  | 变更审计链 (规范§6 留痕可溯) ?limit=50 |
| andromeda_param_routes.p | def api_param_set | 函数 |  | 创建/修改参数 — 仅 super_admin (规范§6.1) |
| andromeda_param_routes.p | def api_param_delete | 函数 |  | 删除参数 — 仅 super_admin + 审计留痕 |
| andromeda_param_routes.p | def api_param_scan | 函数 |  | 手动触发参数健康巡检 (登录可触发, 修改无需权限—只读扫描+落库) |
| auto_eigenflux_arduino_a | def scan_ports | 函数 |  | 扫描所有可用串口并识别Arduino硬件 |
| auto_eigenflux_arduino_a | def start_monitoring | 函数 |  | 启动后台端口监听线程 |
| auto_eigenflux_arduino_a | def stop_monitoring | 函数 |  | 停止端口监听 |
| auto_eigenflux_arduino_a | def read_serial | 函数 |  | 读取串口数据（真实pyserial读取） |
| auto_eigenflux_self_heal | def scan_syntax_errors | 函数 |  | 使用 ast.parse 检查语法错误（仅扫描核心目录） |
| auto_eigenflux_self_heal | def scan_pycache | 函数 |  | 检测 __pycache__ 目录 |
| auto_eigenflux_self_heal | def scan_pyc_files | 函数 |  | 检测孤立的 .pyc 文件 |
| auto_eigenflux_self_heal | def scan_large_logs | 函数 |  | 检测大日志文件 |
| auto_eigenflux_self_heal | def scan_missing_init | 函数 |  | 检测缺失 __init__.py 的Python包目录 |
| auto_eigenflux_self_heal | def scan_db_integrity | 函数 |  | 检测数据库完整性 |
| auto_eigenflux_self_heal | def scan_disk_space | 函数 |  | 检测磁盘空间 |
| auto_eigenflux_self_heal | def scan_temp_files | 函数 |  | 检测临时文件 |
| auto_eigenflux_self_heal | def scan_missing_indexes | 函数 |  | 检测数据库表中缺失的索引 |
| auto_eigenflux_self_heal | def scan_import_errors | 函数 |  | 使用ast.parse检查Python文件导入的模块是否存在 |
| auto_eigenflux_self_heal | def scan_log_errors | 函数 |  | 扫描日志文件中的ERROR/CRITICAL行 |
| auto_eigenflux_self_heal | def scan_empty_files | 函数 |  | 检测空的Python文件（0字节） |
| auto_eigenflux_self_heal | def scan_stale_sessions | 函数 |  | 检测数据库中的过期会话记录 |
| auto_eigenflux_self_heal | def scan_broken_templates | 函数 |  | 检测路由引用的模板文件是否存在 |
| auto_eigenflux_self_heal | def scan_all | 函数 |  | 执行全部扫描 |
| eigenflux_routes.py | def center_stats | 函数 |  | EigenFlux 中心统计 (注册专家/在线/消息/任务) |
| eigenflux_routes.py | def experts | 函数 |  | EigenFlux 专家列表 (支持搜索) |
| eigenflux_routes.py | def messages | 函数 |  | EigenFlux 通信消息列表 |
| eigenflux_routes.py | def tasks | 函数 |  | EigenFlux 协作任务列表 |
| eigenflux_routes.py | def teams | 函数 |  | EigenFlux 专家团队 (按 team_id 分组) |
| eigenflux_routes.py | def stats_overview | 函数 |  |  |
<!-- AUTO-GENERATED-END:functions -->

## 6. 依赖关系
<!-- AUTO-GENERATED-START:deps -->
- 仙女座 ← 冰山 (接收意识脉冲作为进化触发器)
- 仙女座 → 冰山 (自我修正能力驱动冰山阈值自动调节)
- 仙女座 ← 古灵阁 (collab_bus 协作总线消息)
- 仙女座 → mt_collab_bus_events (发布协作事件)
- 仙女座 → mt_andromeda_workflow_runs (工作流执行记录)
- 仙女座 ← mt_collab_bus_subscribers (订阅协作总线)
**扫描统计**: 56 模块 | 212 表 | 191 路由
<!-- AUTO-GENERATED-END:deps -->
