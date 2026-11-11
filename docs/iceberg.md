# 冰山 Iceberg 系统说明

> 自动生成时间: 2026-11-11 15:00
> 系统哈希: 636f97a70957aeb2... (变更时更新)
> 源码路径: engines/iceberg_command.py, engines/iceberg_qbank_adaptive.py, engines/iceberg_schema_seeder.py, engines/iceberg_arduino_ai.py, engines/iceberg_slang_substitution.py

## 1. 系统概述
<!-- AUTO-GENERATED-START:overview -->
🧊 Iceberg API Completer Blueprint (flow_iceberg_20261108)
========================================================
补齐冰山 21 模板所需的 12 张新表的 API 端点:

员工管理
  GET  /api/iceberg/employees                → mt_ai_employees
  GET  /api/iceberg/employees/<id>           → 单员工 + skills + achievements
  GET  /api/iceberg/employees/<id>/chat      → mt_employee_chat
  POST /api/iceberg/employees/<id>/chat      →

**模块数**: 23 | **类**: 7 | **顶层函数**: 203
<!-- AUTO-GENERATED-END:overview -->

## 2. 架构图 (ASCII)
<!-- AUTO-GENERATED-START:arch -->
  ╔══════════════════════════════════════════════════════════╗
  ║  冰山 Iceberg                                      ║
  ╠══════════════════════════════════════════════════════════╣
  ║                                                          ║
  ║  ┌─ 入口 API ──────────────────────────────────────────┐  ║
  ║  │  ANY /api/iceberg/employees                            │  ║
  ║  │  ANY /api/iceberg/employees/<employee_id>              │  ║
  ║  │  ANY /api/iceberg/employees/<employee_id>/chat         │  ║
  ║  │  ANY /api/iceberg/qbank/exam/generate                  │  ║
  ║  │  ANY /api/iceberg/qbank/kps                            │  ║
  ║  └─────────────────────────────────────────────────────┘  ║
  ║                          │                               ║
  ║                          ▼                               ║
  ║  ┌─ 核心引擎 ──────────────────────────────────────────┐  ║
  ║  │  AdaptiveSession                                       │  ║
  ║  │  IcebergSchemaSeeder                                   │  ║
  ║  │  ArduinoAIIntuner                                      │  ║
  ║  │  HandshakeConfig                                       │  ║
  ║  │  NodeState                                             │  ║
  ║  └─────────────────────────────────────────────────────┘  ║
  ║                          │                               ║
  ║                          ▼                               ║
  ║  ┌─ 数据库表 ──────────────────────────────────────────┐  ║
  ║  │  mt_center_boundary                                    │  ║
  ║  │  mt_center_cognition_portrait                          │  ║
  ║  │  mt_center_direction_execution                         │  ║
  ║  │  mt_center_direction_pool                              │  ║
  ║  │  mt_center_evolution_log                               │  ║
  ║  │  mt_center_exec_log                                    │  ║
  ║  └─────────────────────────────────────────────────────┘  ║
  ║                                                          ║
  ╚══════════════════════════════════════════════════════════╝
<!-- AUTO-GENERATED-END:arch -->

## 3. API 端点
<!-- AUTO-GENERATED-START:api -->
| 蓝图 | 方法 | URL | 处理函数 | 说明 |
|------|------|-----|----------|------|
| iceberg_bp | ANY | /api/iceberg/achievements | list_achievements | GET /api/iceberg/achievements?employee=< |
| iceberg_bp | ANY | /api/iceberg/audit | api_audit |  |
| iceberg_bp | ANY | /api/iceberg/badges | list_badges | GET /api/iceberg/badges |
| iceberg_bp | ANY | /api/iceberg/badges/<category> | list_badges_by_categ | GET /api/iceberg/badges/<category> |
| iceberg_bp | ANY | /api/iceberg/badges/check | check_badges | POST /api/iceberg/badges/check — 检查活跃员工是 |
| iceberg_bp | ANY | /api/iceberg/bindings/<domain_key>/<self | api_binding_toggle | body: {"enabled": false, "reason": "临时停用 |
| iceberg_bp | ANY | /api/iceberg/daemons | api_daemons | 五自相关 daemon 的心跳状态 (读 mt_daemon_registry) |
| iceberg_bp | ANY | /api/iceberg/domain_health | api_domain_health | 手动覆盖某域健康分 body: {"domain": "education",  |
| iceberg_bp | ANY | /api/iceberg/domains | api_domains |  |
| iceberg_bp | ANY | /api/iceberg/domains/<domain_key> | api_domain_detail |  |
| iceberg_bp | ANY | /api/iceberg/employees | list_employees | GET /api/iceberg/employees — 列表 (filter: |
| iceberg_bp | ANY | /api/iceberg/employees/<employee_id> | get_employee | GET /api/iceberg/employees/<id> — 单员工详情  |
| iceberg_bp | ANY | /api/iceberg/employees/<employee_id>/cha | get_employee_chat | GET /api/iceberg/employees/<id>/chat — 历 |
| iceberg_bp | ANY | /api/iceberg/evolve/<self_key> | api_evolve | 手动触发某自能力 — 跑意识脉冲 + 调用对应 daemon 入口 (若可调用) |
| iceberg_bp | ANY | /api/iceberg/health | iceberg_health | GET /api/iceberg/health — 所有冰山表的行数 + 状态 |
| iceberg_bp | ANY | /api/iceberg/lang/grammar/practice | grammar_practice | GET/POST /api/iceberg/lang/grammar/pract |
| iceberg_bp | ANY | /api/iceberg/lang/sessions | list_lang_sessions | GET /api/iceberg/lang/sessions?employee_ |
| iceberg_bp | ANY | /api/iceberg/lang/vocab/due | vocab_due | GET /api/iceberg/lang/vocab/due — 记忆曲线到期 |
| iceberg_bp | ANY | /api/iceberg/matrix | api_matrix |  |
| iceberg_bp | ANY | /api/iceberg/optimizations | api_optimizations |  |
| iceberg_bp | ANY | /api/iceberg/pulse | api_pulse |  |
| iceberg_bp | ANY | /api/iceberg/qbank/exam/generate | generate_exam | POST /api/iceberg/qbank/exam/generate —  |
| iceberg_bp | ANY | /api/iceberg/qbank/kps | list_kps | GET /api/iceberg/qbank/kps?subject=<sid> |
| iceberg_bp | ANY | /api/iceberg/qbank/questions | list_questions | GET /api/iceberg/qbank/questions?subject |
| iceberg_bp | ANY | /api/iceberg/qbank/subjects | list_subjects | GET /api/iceberg/qbank/subjects |
| iceberg_bp | ANY | /api/iceberg/qbank/subjects/<subject_id> | get_subject | GET /api/iceberg/qbank/subjects/<id> — 学 |
| iceberg_bp | ANY | /api/iceberg/runs | api_runs |  |
| iceberg_bp | ANY | /api/iceberg/runs/<int:run_id> | api_run_delete |  |
| iceberg_bp | ANY | /api/iceberg/self | api_self |  |
| iceberg_bp | ANY | /api/iceberg/skills/leaderboard | skill_leaderboard | GET /api/iceberg/skills/leaderboard — TO |
| iceberg_bp | ANY | /api/iceberg/skills/usage | list_skill_usage | GET /api/iceberg/skills/usage?skill_id=& |
| iceberg_bp | ANY | /api/iceberg/thresholds | api_thresholds |  |
| iceberg_bp | ANY | /iceberg/center | iceberg_center |  |
| mobile_icebe | ANY | /api/iceberg/admin/actions | api_admin_actions | 管理员操作: restart_daemon / stop_daemon / pi |
| mobile_icebe | ANY | /api/iceberg/admin/daemons | api_admin_daemons | daemon 注册表 + 运行状态 (smart_mount_processes |
| mobile_icebe | ANY | /api/iceberg/admin/health | api_admin_health | 系统健康快照 |
| mobile_icebe | ANY | /api/iceberg/ble/arduino | api_ble_arduino | Arduino 已检测设备 |
| mobile_icebe | ANY | /api/iceberg/ble/devices | api_ble_devices | 已扫描的 BLE 设备清单 (Flask DB 历史) |
| mobile_icebe | ANY | /api/iceberg/ble/gatt/<addr> | api_ble_gatt | 单台设备的 GATT 缓存详情 |
| mobile_icebe | ANY | /api/iceberg/daemon_status | api_daemon_status | 两个关键 daemon 是否在跑 |
| mobile_icebe | ANY | /api/iceberg/empower_mobile | api_empower_mobile | 赋能状态 (移动端轻量) |
| mobile_icebe | ANY | /api/iceberg/mobile | api_mobile_status | 聚合返回冰山核心状态 |
| mobile_icebe | ANY | /api/iceberg/new_directions | api_new_directions | 自发明方向列表 |
| mobile_icebe | ANY | /apk | apk_landing | 📱 APK 下载引导页 (小米 13 / 所有手机) |
| mobile_icebe | ANY | /apk/binary | serve_apk_binary | 真正的 APK 二进制下载 — send_from_directory 绕过拦截 |
| mobile_icebe | ANY | /apk/download | serve_apk_binary | 真正的 APK 二进制下载 — send_from_directory 绕过拦截 |
| mobile_icebe | ANY | /iceberg/mobile | page_mobile | 🧊 冰山移动管理端页面 |
<!-- AUTO-GENERATED-END:api -->

## 4. 数据库表
<!-- AUTO-GENERATED-START:tables -->
### mt_center_boundary (37 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| boundary_id | TEXT | ✓ | 是 |
| center_name | TEXT |  | 否 |
| can_do | TEXT |  | 是 |
| cannot_do | TEXT |  | 是 |
| recent_violations | INTEGER |  | 是 |
| last_violation | TEXT |  | 是 |
| ollama_reasoning | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_center_cognition_portrait (37 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| portrait_id | TEXT | ✓ | 是 |
| center_name | TEXT |  | 否 |
| galaxy | TEXT |  | 是 |
| primary_duty | TEXT |  | 是 |
| secondary_duty | TEXT |  | 是 |
| boundaries | TEXT |  | 是 |
| ai_route | TEXT |  | 是 |
| event_distribution | TEXT |  | 是 |
| collab_frequency | TEXT |  | 是 |
| health_score | REAL |  | 是 |
| ollama_generated | INTEGER |  | 是 |
| generated_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_center_direction_execution (3,016 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| exec_id | INTEGER | ✓ | 是 |
| direction_id | INTEGER |  | 是 |
| center_name | TEXT |  | 是 |
| direction_title | TEXT |  | 是 |
| phase | TEXT |  | 是 |
| plan_summary | TEXT |  | 是 |
| auto_spawned_tasks | INTEGER |  | 是 |
| tasks_completed | INTEGER |  | 是 |
| evidence | TEXT |  | 是 |
| started_at | TEXT |  | 是 |
| completed_at | TEXT |  | 是 |

### mt_center_direction_pool (3,016 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| direction_id | INTEGER | ✓ | 是 |
| center_name | TEXT |  | 是 |
| direction_title | TEXT |  | 是 |
| seed | TEXT |  | 是 |
| status | TEXT |  | 是 |
| priority | INTEGER |  | 是 |
| auto_spawned | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_center_evolution_log (144,181 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| log_id | INTEGER | ✓ | 是 |
| center_name | TEXT |  | 是 |
| event | TEXT |  | 是 |
| detail | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_center_exec_log (82 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| center_code | TEXT |  | 是 |
| action | TEXT |  | 是 |
| detail | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_center_experience (181 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| exp_id | TEXT | ✓ | 是 |
| center_name | TEXT |  | 否 |
| exp_type | TEXT |  | 否 |
| summary | TEXT |  | 是 |
| lesson | TEXT |  | 是 |
| confidence | REAL |  | 是 |
| source_events | TEXT |  | 是 |
| applicable_engines | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_center_health_matrix (2,521 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| matrix_id | TEXT | ✓ | 是 |
| check_time | TEXT |  | 是 |
| center_andromeda | REAL |  | 是 |
| center_gobelin | REAL |  | 是 |
| center_iceberg | REAL |  | 是 |
| center_eigenflux | REAL |  | 是 |
| center_eventbus | REAL |  | 是 |
| center_audit | REAL |  | 是 |
| center_brainfeed | REAL |  | 是 |
| center_taskhall | REAL |  | 是 |
| center_hr | REAL |  | 是 |
| center_autopilot | REAL |  | 是 |
| total_score | REAL |  | 是 |
| overall_status | TEXT |  | 是 |
| details | TEXT |  | 是 |
| bottlenecks | TEXT |  | 是 |
| suggestions | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_center_knowledge_digest (6,646 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| digest_id | INTEGER | ✓ | 是 |
| center_name | TEXT |  | 是 |
| digest_type | TEXT |  | 是 |
| digest_summary | TEXT |  | 是 |
| kp_count | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_center_knowledge_points (4,781 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| kp_id | INTEGER | ✓ | 是 |
| center_name | TEXT |  | 是 |
| kp_type | TEXT |  | 是 |
| source_table | TEXT |  | 是 |
| source_row_id | INTEGER |  | 是 |
| knowledge_title | TEXT |  | 是 |
| knowledge_body | TEXT |  | 是 |
| confidence | REAL |  | 是 |
| applied | INTEGER |  | 是 |
| applied_at | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_center_meetings (25 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| meeting_id | TEXT |  | 否 |
| center_code | TEXT |  | 否 |
| center_name | TEXT |  | 否 |
| meeting_type | TEXT |  | 否 |
| meeting_title | TEXT |  | 否 |
| host_ai | TEXT |  | 是 |
| attendees | TEXT |  | 否 |
| agenda | TEXT |  | 是 |
| status | TEXT |  | 是 |
| started_at | TEXT |  | 是 |
| last_heartbeat | TEXT |  | 是 |
| ended_at | TEXT |  | 是 |
| source | TEXT |  | 是 |

### mt_center_proposal_consultations (276,672 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| consult_id | INTEGER | ✓ | 是 |
| hall_task_id | INTEGER |  | 否 |
| center_id | INTEGER |  | 否 |
| center_code | TEXT |  | 否 |
| center_name | TEXT |  | 否 |
| perspective_type | TEXT |  | 否 |
| perspective_text | TEXT |  | 否 |
| match_score | REAL |  | 是 |
| created_at | TEXT |  | 是 |
| flow_id | TEXT |  | 是 |

### mt_center_pulse (70,963 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| pulse_id | INTEGER | ✓ | 是 |
| center_name | TEXT |  | 否 |
| health_score | INTEGER |  | 是 |
| status | TEXT |  | 是 |
| active_tasks | INTEGER |  | 是 |
| queue_depth | INTEGER |  | 是 |
| tables_checked | INTEGER |  | 是 |
| anomalies_found | INTEGER |  | 是 |
| rnd_directions | INTEGER |  | 是 |
| detail | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_center_registry (33 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| code | TEXT |  | 否 |
| name | TEXT |  | 是 |
| description | TEXT |  | 是 |
| layer | TEXT |  | 是 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| cycle | TEXT |  | 是 |
| role | TEXT |  | 是 |
| last_run | TEXT |  | 是 |
| load | TEXT |  | 是 |
| avg_cpu | TEXT |  | 是 |
| avg_mem | TEXT |  | 是 |
| health_score | TEXT |  | 是 |

### mt_center_self_check (114,971 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| check_id | INTEGER | ✓ | 是 |
| center_name | TEXT |  | 否 |
| check_type | TEXT |  | 否 |
| target | TEXT |  | 是 |
| metric | TEXT |  | 是 |
| metric_value | REAL |  | 是 |
| threshold | REAL |  | 是 |
| result | TEXT |  | 是 |
| auto_repaired | INTEGER |  | 是 |
| repair_task_id | INTEGER |  | 是 |
| detail | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_iceberg_achievement (20 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| achievement_id | TEXT | ✓ | 是 |
| badge_id | TEXT |  | 否 |
| employee_id | TEXT |  | 是 |
| center | TEXT |  | 是 |
| context_json | TEXT |  | 是 |
| earned_at | TEXT |  | 是 |

### mt_iceberg_admin_audit (8 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| username | TEXT |  | 否 |
| action | TEXT |  | 否 |
| target | TEXT |  | 否 |
| detail_json | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_iceberg_badge (18 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| badge_id | TEXT | ✓ | 是 |
| badge_name | TEXT |  | 否 |
| badge_category | TEXT |  | 是 |
| icon_emoji | TEXT |  | 是 |
| description | TEXT |  | 是 |
| condition_json | TEXT |  | 是 |
| rarity | REAL |  | 是 |
| created_at | TEXT |  | 是 |

### mt_iceberg_binding_override (2 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| domain_key | TEXT |  | 否 |
| self_key | TEXT |  | 否 |
| enabled | INTEGER |  | 否 |
| health_override | REAL |  | 是 |
| reason | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |
| updated_by | TEXT |  | 是 |

### mt_iceberg_consciousness_optimizations (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| run_id | TEXT |  | 是 |
| domain | TEXT |  | 是 |
| self_capability | TEXT |  | 是 |
| suggestion | TEXT |  | 是 |
| confidence | REAL |  | 是 |
| action_taken | INTEGER |  | 是 |
| created_at | TEXT |  | 是 |

### mt_iceberg_consciousness_runs (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| run_id | TEXT |  | 是 |
| run_type | TEXT |  | 是 |
| domain | TEXT |  | 是 |
| health_score | REAL |  | 是 |
| five_self_status | TEXT |  | 是 |
| brain_feed_delta | INTEGER |  | 是 |
| proposals_delta | INTEGER |  | 是 |
| evolution_trigger | INTEGER |  | 是 |
| evolution_decision | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_iceberg_content_matrix (687 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| content_key | TEXT |  | 否 |
| domain | TEXT |  | 否 |
| lang | TEXT |  | 否 |
| audience | TEXT |  | 否 |
| context_tag | TEXT |  | 否 |
| text | TEXT |  | 否 |
| token_count | INTEGER |  | 否 |
| token_weight | REAL |  | 否 |
| embedding | BLOB |  | 是 |
| embedding_dim | INTEGER |  | 是 |
| priority | INTEGER |  | 否 |
| version | TEXT |  | 否 |
| source | TEXT |  | 否 |
| remark | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |

### mt_iceberg_threshold_configs (10 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| threshold_key | TEXT |  | 否 |
| value | INTEGER |  | 否 |
| description | TEXT |  | 是 |
| updated_at | TEXT |  | 是 |
| updated_by | TEXT |  | 是 |

### mt_lab_centers (19 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| id | INTEGER | ✓ | 是 |
| center_code | TEXT |  | 否 |
| name | TEXT |  | 否 |
| domain | TEXT |  | 否 |
| keywords | TEXT |  | 否 |
| status | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_medical_center_bugs (8 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| bug_id | TEXT | ✓ | 是 |
| report_id | TEXT |  | 是 |
| target | TEXT |  | 否 |
| category | TEXT |  | 否 |
| severity | TEXT |  | 是 |
| description | TEXT |  | 否 |
| fix_suggestion | TEXT |  | 是 |
| auto_fixed | INTEGER |  | 是 |
| fix_status | TEXT |  | 是 |
| fixed_at | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_medical_center_reports (3 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| report_id | TEXT | ✓ | 是 |
| target | TEXT |  | 否 |
| exam_level | TEXT |  | 否 |
| trigger_type | TEXT |  | 否 |
| health_score | INTEGER |  | 是 |
| overall_status | TEXT |  | 是 |
| dimensions | TEXT |  | 是 |
| bugs_found | INTEGER |  | 是 |
| suggestions | TEXT |  | 是 |
| report_json | TEXT |  | 是 |
| hall_task_id | TEXT |  | 是 |
| created_at | TEXT |  | 是 |

### mt_medical_center_skill_registry (0 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| skill_id | TEXT | ✓ | 是 |
| name | TEXT |  | 否 |
| type | TEXT |  | 否 |
| target_center | TEXT |  | 否 |
| trigger_event | TEXT |  | 是 |
| last_checked | TEXT |  | 是 |
| health_status | TEXT |  | 是 |
| version_info | TEXT |  | 是 |
| registered_at | TEXT |  | 是 |

### mt_version_center (18 行)
| 列 | 类型 | PK | 可空 |
|----|------|:--:|:----:|
| version_id | TEXT | ✓ | 是 |
| component | TEXT |  | 否 |
| old_version | TEXT |  | 是 |
| new_version | TEXT |  | 否 |
| bump_type | TEXT |  | 否 |
| trigger_event | TEXT |  | 是 |
| trigger_source | TEXT |  | 是 |
| trigger_payload | TEXT |  | 是 |
| changelog | TEXT |  | 是 |
| version_suffix | TEXT |  | 是 |
| created_at | TEXT |  | 是 |
<!-- AUTO-GENERATED-END:tables -->

## 5. 引擎函数清单
<!-- AUTO-GENERATED-START:functions -->
| 文件 | 类/函数 | 类型 | 参数 | 说明 |
|------|---------|------|------|------|
| iceberg_archive_bp.py | def _rows | 函数 | db, sql, args | 安全查询: 库/表缺失一律返回空列表, 不让档案馆整体 500 |
| iceberg_archive_bp.py | def _count | 函数 | db, table, where |  |
| iceberg_archive_bp.py | def _has_table | 函数 | db, table |  |
| iceberg_archive_bp.py | def _q_version | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_evolution | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_flow | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_task | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_rule | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_upgrade | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_copy | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _timeline | 函数 | kind, q, limit |  |
| iceberg_archive_bp.py | def _overview | 函数 |  |  |
| iceberg_archive_bp.py | def archive_page | 函数 |  |  |
| iceberg_archive_bp.py | def archive_overview | 函数 |  |  |
| iceberg_archive_bp.py | def archive_timeline | 函数 |  |  |
| iceberg_archive_bp.py | def archive_detail | 函数 |  |  |
| iceberg_archive_bp.py | def archive_search | 函数 |  |  |
| iceberg_archive_bp.py | def archive_stats | 函数 |  |  |
| tokens.py | def as_css_vars | 函数 |  | 导出 CSS custom properties — 在 <style> 里直接 |
| tokens.py | def layer | 函数 | layer_name | 快捷访问某层配置。 |
| iceberg_archive_bp.py | def _rows | 函数 | db, sql, args | 安全查询: 库/表缺失一律返回空列表, 不让档案馆整体 500 |
| iceberg_archive_bp.py | def _count | 函数 | db, table, where |  |
| iceberg_archive_bp.py | def _has_table | 函数 | db, table |  |
| iceberg_archive_bp.py | def _q_version | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_evolution | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_flow | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_task | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_rule | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_upgrade | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_copy | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _timeline | 函数 | kind, q, limit |  |
| iceberg_archive_bp.py | def _overview | 函数 |  |  |
| iceberg_archive_bp.py | def archive_page | 函数 |  |  |
| iceberg_archive_bp.py | def archive_overview | 函数 |  |  |
| iceberg_archive_bp.py | def archive_timeline | 函数 |  |  |
| iceberg_archive_bp.py | def archive_detail | 函数 |  |  |
| iceberg_archive_bp.py | def archive_search | 函数 |  |  |
| iceberg_archive_bp.py | def archive_stats | 函数 |  |  |
| tokens.py | def as_css_vars | 函数 |  | 导出 CSS custom properties — 在 <style> 里直接 |
| tokens.py | def layer | 函数 | layer_name | 快捷访问某层配置。 |
| iceberg_api_completer_bp | def _get_conn | 函数 |  | 获取 DB 连接 (WAL + 长 timeout 应对并发守护进程) |
| iceberg_api_completer_bp | def _row_to_dict | 函数 | row |  |
| iceberg_api_completer_bp | def _rows_to_list | 函数 | rows |  |
| iceberg_api_completer_bp | def _ok | 函数 | data, **kw |  |
| iceberg_api_completer_bp | def _err | 函数 | msg, code |  |
| iceberg_api_completer_bp | def _ollama | 函数 | prompt, model, timeout | 调用本地 Ollama, 返回纯文本 |
| iceberg_api_completer_bp | def list_employees | 函数 |  | GET /api/iceberg/employees — 列表 (filter: |
| iceberg_api_completer_bp | def get_employee | 函数 | employee_id | GET /api/iceberg/employees/<id> — 单员工详情  |
| iceberg_api_completer_bp | def get_employee_chat | 函数 | employee_id | GET /api/iceberg/employees/<id>/chat — 历 |
| iceberg_api_completer_bp | def employee_chat | 函数 | employee_id | POST /api/iceberg/employees/<id>/chat —  |
| iceberg_api_completer_bp | def list_subjects | 函数 |  | GET /api/iceberg/qbank/subjects |
| iceberg_api_completer_bp | def get_subject | 函数 | subject_id | GET /api/iceberg/qbank/subjects/<id> — 学 |
| iceberg_api_completer_bp | def list_kps | 函数 |  | GET /api/iceberg/qbank/kps?subject=<sid> |
| iceberg_api_completer_bp | def list_questions | 函数 |  | GET /api/iceberg/qbank/questions?subject |
| iceberg_api_completer_bp | def generate_exam | 函数 |  | POST /api/iceberg/qbank/exam/generate —  |
| iceberg_api_completer_bp | def list_badges | 函数 |  | GET /api/iceberg/badges |
| iceberg_api_completer_bp | def list_badges_by_category | 函数 | category | GET /api/iceberg/badges/<category> |
| iceberg_api_completer_bp | def list_achievements | 函数 |  | GET /api/iceberg/achievements?employee=< |
| iceberg_api_completer_bp | def check_badges | 函数 |  | POST /api/iceberg/badges/check — 检查活跃员工是 |
| iceberg_api_completer_bp | def list_skill_usage | 函数 |  | GET /api/iceberg/skills/usage?skill_id=& |
| iceberg_api_completer_bp | def skill_leaderboard | 函数 |  | GET /api/iceberg/skills/leaderboard — TO |
| iceberg_api_completer_bp | def list_lang_sessions | 函数 |  | GET /api/iceberg/lang/sessions?employee_ |
| iceberg_api_completer_bp | def vocab_due | 函数 |  | GET /api/iceberg/lang/vocab/due — 记忆曲线到期 |
| iceberg_api_completer_bp | def grammar_practice | 函数 |  | GET/POST /api/iceberg/lang/grammar/pract |
| iceberg_api_completer_bp | def iceberg_health | 函数 |  | GET /api/iceberg/health — 所有冰山表的行数 + 状态 |
| iceberg_archive_bp.py | def _rows | 函数 | db, sql, args | 安全查询: 库/表缺失一律返回空列表, 不让档案馆整体 500 |
| iceberg_archive_bp.py | def _count | 函数 | db, table, where |  |
| iceberg_archive_bp.py | def _has_table | 函数 | db, table |  |
| iceberg_archive_bp.py | def _q_version | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_evolution | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_flow | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_task | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_rule | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_upgrade | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _q_copy | 函数 | q, limit |  |
| iceberg_archive_bp.py | def _timeline | 函数 | kind, q, limit |  |
| iceberg_archive_bp.py | def _overview | 函数 |  |  |
| iceberg_archive_bp.py | def archive_page | 函数 |  |  |
| iceberg_archive_bp.py | def archive_overview | 函数 |  |  |
| iceberg_archive_bp.py | def archive_timeline | 函数 |  |  |
| iceberg_archive_bp.py | def archive_detail | 函数 |  |  |
| iceberg_archive_bp.py | def archive_search | 函数 |  |  |
| iceberg_archive_bp.py | def archive_stats | 函数 |  |  |
| tokens.py | def as_css_vars | 函数 |  | 导出 CSS custom properties — 在 <style> 里直接 |
| tokens.py | def layer | 函数 | layer_name | 快捷访问某层配置。 |
| workflows.py | def _get_app_db | 函数 |  |  |
| workflows.py | def _iceberg_import | 函数 | module_name | 惰性 import iceberg 子模块 (避免一次性加载 240KB). |
| workflows.py | def _run_iceberg_loop | 函数 | loop_name, db_path | 代理 iceberg_command.py 的 _loop_* 函数. |
| workflows.py | def _h_iceberg_upgrade | 函数 | input |  |
| workflows.py | def _h_iceberg_ops | 函数 | input |  |
| workflows.py | def _h_iceberg_derive | 函数 | input |  |
| workflows.py | def _h_iceberg_strengthen | 函数 | input |  |
| workflows.py | def _h_iceberg_expand | 函数 | input |  |
| workflows.py | def _h_iceberg_research | 函数 | input |  |
| workflows.py | def _h_handshake | 函数 | input | wf_iceberg_handshake — AI 节点握手状态查询. |
| workflows.py | def _h_qbank_adaptive | 函数 | input | wf_iceberg_qbank_adaptive — 自适应题库生成. |
| workflows.py | def _h_slang_substitute | 函数 | input | wf_iceberg_slang_substitute — 网络语替换. |
| workflows.py | def _h_arduino_ai | 函数 | input | wf_iceberg_arduino_ai — Arduino AI 代码生成. |
| workflows.py | def _h_consciousness | 函数 | input | wf_iceberg_consciousness — 冰山意识脉冲 + 域统计. |
| workflows.py | def register_workflows | 函数 | registry, register_fn | 冰山系统域 — 6 大自动能力 + 7 子模块桥接. |
| iceberg_arduino_ai.py | **class ArduinoAIIntuner** | 类 | | AI 自动干预 — 检测问题 → 自动修复 → 记录日志 |
| | ↳ def __init__ | 方法 | self, db |  |
| | ↳ def scan_and_fix | 方法 | self | 扫描所有 Arduino 表 → 自动修复空壳 + 记录 |
| | ↳ def _extract_and_upsert_port | 方法 | self, details_json |  |
| | ↳ def _guess_board | 方法 | self, vid, pid |  |
| | ↳ def _log_intervention | 方法 | self, action, detail |  |
| iceberg_arduino_ai.py | def ensure_tables | 函数 | db | 增量补齐 |
| iceberg_arduino_ai.py | def ollama | 函数 | sys_p, user_p, timeout |  |
| iceberg_arduino_ai.py | def ai_generate_code | 函数 | prompt, board | AI 生成 Arduino 代码 |
| iceberg_arduino_ai.py | def _mock_compile | 函数 | code | 模拟编译 (真实设备接上就用 arduino-cli) |
| iceberg_arduino_ai.py | def ai_analyze_compile_error | 函数 | error_text | AI 分析编译错误 → 根因 + 修复建议 |
| iceberg_arduino_ai.py | def run_demo | 函数 |  |  |
| iceberg_command.py | def ollama | 函数 | sys_p, user_p, timeout |  |
| iceberg_command.py | def _ensure_tables | 函数 | db |  |
| iceberg_command.py | def _loop_upgrade | 函数 | db | 🛡️ 能力1: 自动升级 — 规则版本一致性 + 弱约束词清零 |
| iceberg_command.py | def _loop_ops | 函数 | db | 🧱 能力2: 自动运维 — 违规告警 + 审计日志清理 |
| iceberg_command.py | def _loop_derive | 函数 | db | 🧬 能力3: 自动衍生 — 从违规案例 Q5 生成新规则 |
| iceberg_command.py | def _loop_strengthen | 函数 | db | 💪 能力4: 自动强化 — 已有规则引擎总指挥 |
| iceberg_command.py | def _loop_expand | 函数 | db | 🔭 能力5: 自动拓展 — 违规模式 → 新规则自动部署 |
| iceberg_command.py | def _loop_research | 函数 | db | 🔬 能力6: 自动研究 — Q5 研究新威胁/绕过 |
| iceberg_command.py | def run_iceberg_cycle | 函数 |  | 冰山 6 大能力一轮跑完 |
| iceberg_command.py | def log | 函数 | msg |  |
| iceberg_consciousness.py | **class IcebergConsciousness** | 类 | | 🧊 仙女座 × 冰山 意识引擎

v26.1: 混入 BaseEngine 能力 |
| | ↳ def logger | 方法 | self |  |
| | ↳ def emit_event | 方法 | self, event_name, target, payl | 发射事件到 EventBus (BaseEngine 标准签名) |
| | ↳ def health_check | 方法 | self | 标准健康字典 |
| | ↳ def __init__ | 方法 | self, db_path |  |
| | ↳ def pulse | 方法 | self |  |
| | ↳ def _decide_upgrade_directio | 方法 | self, c, total_score, domain_c | 综合 7 域健康 + AI 员工活跃 + 脑库类型 + 提案方向, 输出具体升级 |
| | ↳ def _ensure_direction_regist | 方法 | self, c | 维护 mt_iceberg_direction_registry 表, 方向1/ |
| | ↳ def _execute_upgrade_directi | 方法 | self, c, run_id, decision, dir | 根据方向描述分派到具体升级动作执行器, 真做事 + 记录 |
| | ↳ def _incubate_new_direction | 方法 | self, c, run_id, current_dir_n | 🆕 冰山方向孵化器
触发条件: 脑库 >= 520 + decision upg |
| | ↳ def _score_domain | 方法 | self, domain, tables |  |
| | ↳ def _count | 方法 | self, table |  |
| | ↳ def recent_runs | 方法 | self, limit |  |
| iceberg_content_matrix.p | def _resolve_db | 函数 |  |  |
| iceberg_content_matrix.p | def _conn | 函数 |  |  |
| iceberg_content_matrix.p | def tokenize | 函数 | text |  |
| iceberg_content_matrix.p | def ensure_matrix_table | 函数 |  |  |
| iceberg_content_matrix.p | def migrate_from_legacy_i18n | 函数 | progress_cb | 把 mt_i18n_keys 的 1440 条迁移进新矩阵表。
旧表保留（向后兼 |
| iceberg_content_matrix.p | def get_content | 函数 | key, lang, audience, context,  | 按多维切片检索文案，失败自动降级。 |
| iceberg_content_matrix.p | def get_i18n_dict | 函数 | lang, domain, audience | 构建 {key: text} 字典给前端 JS 使用（与 i18n_engine |
| iceberg_content_matrix.p | def token_budget | 函数 | domain, audience, lang | 返回某域 / 受众 / 语言切片的 token 预算。
用于 LLM conte |
| iceberg_content_matrix.p | def store_content | 函数 | key, text, lang, domain, audie | 单条写入（INSERT OR REPLACE 多维切片）。 |
| iceberg_content_matrix.p | def store_content_4lang | 函数 | key, zh, tw, ja, en, domain, * | 四语言一键写入（t() 种子场景最常用）。 |
| iceberg_content_matrix.p | def matrix_stats | 函数 |  |  |
| iceberg_content_matrix.p | def bootstrap | 函数 | force_remigrate | Flask 启动时调用。 |
| iceberg_content_matrix.p | def iceberg_inject_i18n_into | 函数 | app | 向 Flask app 的 Jinja2 注入冰山引擎驱动的 t() / t_k |
| iceberg_handshake.py | **class HandshakeConfig** | 类 | | 智能同步配置 — MacBook 主 (MASTER) / Mac mini 辅 |
| | ↳ def my_port | 方法 | self |  |
| | ↳ def remote_port | 方法 | self |  |
| iceberg_handshake.py | **class NodeState** | 类 | |  |
| iceberg_handshake.py | **class HandshakeEngine** | 类 | | Mac mini 自动握手 + 双向同步 + 专家圆桌 |
| | ↳ def __init__ | 方法 | self |  |
| | ↳ def _get_db | 方法 | self | 每个线程独立 DB 连接 (Python 3.14 禁止跨线程共享). |
| | ↳ def db | 方法 | self |  |
| | ↳ def _apply_defaults | 方法 | self |  |
| | ↳ def state | 方法 | self |  |
| | ↳ def _set_state | 方法 | self, new_state, **extra |  |
| | ↳ def ping_remote | 方法 | self, timeout | 发 PING → 等 PONG. 返回远端 capabilities 或 Non |
| | ↳ def serve_forever | 方法 | self | 本地握手服务端 — 接收远端的 HELLO/PING (带 bind retry |
| | ↳ def _my_capabilities | 方法 | self | 本机能力快照. |
| | ↳ def _app_version | 方法 | self |  |
| | ↳ def _rules_version | 方法 | self |  |
| | ↳ def _count_table | 方法 | self, table |  |
| | ↳ def _count_tables_sum | 方法 | self, tables | 多张表 COUNT 合计 (题库 5 表合计). |
| | ↳ def _safe_count | 方法 | self, table | 表不存在也不崩, 返回 0. |
| | ↳ def _safe_daemon_status | 方法 | self | daemon_registry 表不存在也不崩. |
| iceberg_handshake.py | def get_handshake_engine | 函数 |  |  |
| iceberg_handshake.py | def create_handshake_bluepri | 函数 |  | 注册到 Flask app 后: /api/handshake/* 提供报告查询 |
| iceberg_meta_model.py | def build_binding_matrix | 函数 |  | 冰山域 × 九自能力 绑定矩阵 |
| iceberg_meta_model.py | def consciousness_pulse | 函数 |  | 生成一次冰山意识脉冲 (daemon 调) |
| iceberg_meta_model.py | def domain_stats | 函数 | domain_key | 单个冰山域的九自能力绑定详情 (v26.0 向后兼容: 同时返回 nine_se |
| iceberg_qbank_adaptive.p | **class AdaptiveSession** | 类 | | 自适应测试会话 — 根据答题表现动态调整难度 |
| | ↳ def __init__ | 方法 | self, user_id, subject, grade |  |
| | ↳ def next_question | 方法 | self | 根据当前难度生成下一题 |
| | ↳ def submit_answer | 方法 | self, question, user_answer | 提交答案 → 判定 → 调整难度 → 返回下一题 |
| | ↳ def _judge | 方法 | self, correct, user, options | 判分: 归一化精确匹配; 选项题支持序号/字母/选项文本 |
| | ↳ def _is_safe_input | 方法 | self, input_str |  |
| | ↳ def summary | 方法 | self | 会话总结: 总题数/通过率/难度均值/起止难度 |
| iceberg_qbank_adaptive.p | def ollama | 函数 | sys_p, user_p, timeout, retrie |  |
| iceberg_qbank_adaptive.p | def ensure_tables | 函数 | db | 增量补齐表结构 |
| iceberg_qbank_adaptive.p | def ensure_table_structure | 函数 | db, table_name, columns |  |
| iceberg_qbank_adaptive.p | def q5_generate_questions | 函数 | subject, grade, difficulty, co | Q5 本地推理出题 → 结构化 JSON |
| iceberg_qbank_adaptive.p | def _fallback_questions | 函数 | subject, count, difficulty | Q5 不可用时的兜底题目 |
| iceberg_qbank_adaptive.p | def generate_daily_practice | 函数 | db, user_id | 为用户生成今日练习 (5-10 题, 覆盖薄弱点) |
| iceberg_qbank_adaptive.p | def calibrate_difficulty | 函数 | db | 扫描所有答题记录 → 校准每题难度 |
| iceberg_qbank_adaptive.p | def register_routes | 函数 | app | 注册 Flask 路由 |
| iceberg_qbank_adaptive.p | def register_smart_questions | 函数 | app |  |
| iceberg_qbank_adaptive.p | def register_daily_practice_ | 函数 | app |  |
| iceberg_qbank_adaptive.p | def register_calibrate_route | 函数 | app |  |
| iceberg_qbank_adaptive.p | def register_routes_wrapper | 函数 | app, path, methods, handler | 独立注册入口 (供 register_*_route 复用 register_r |
| iceberg_qbank_adaptive.p | def run_demo | 函数 |  | CLI 演示 |
| iceberg_schema_seeder.py | **class IcebergSchemaSeeder** | 类 | | 🧊 冰山 Schema Seeder — 12 张表建表 + 智能 seed |
| | ↳ def __init__ | 方法 | self, db_path |  |
| | ↳ def close | 方法 | self |  |
| | ↳ def create_all_tables | 方法 | self | CREATE TABLE IF NOT EXISTS for all 12 sc |
| | ↳ def seed_ai_employees | 方法 | self | 从 mt_lab_hr_log + mtscos_ai_employees +  |
| | ↳ def seed_employee_skill | 方法 | self | 每个员工分配 3-5 个技能 (从 mt_skill_registry 衍生,  |
| | ↳ def seed_qbank | 方法 | self | 从 mt_iceberg_content_matrix 的 domain 衍生学 |
| | ↳ def seed_badges | 方法 | self | 预设徽章 (不依赖 Ollama, 快速稳定) |
| | ↳ def seed_achievements | 方法 | self | 为前 10 名活跃员工颁发初始徽章 (初代员工 + 工作狂) |
| | ↳ def seed_skill_usage_log | 方法 | self | 从 mt_center_evolution_log (62663 rows) 和 |
| | ↳ def seed_lang_tables | 方法 | self | 生成示例语言学习会话、词汇复习、语法练习 |
| | ↳ def run_full_seed | 方法 | self |  |
| | ↳ def verify_all | 方法 | self |  |
| iceberg_schema_seeder.py | def ollama_generate | 函数 | prompt, model, timeout | 调用本地 Ollama，返回纯文本回复（无 JSON 约束） |
| iceberg_schema_seeder.py | def ensure_iceberg_tables_on | 函数 | conn, run_seed | 给一个已有的 sqlite3 connection, 确保 12 张冰山表都存在 |
| iceberg_schema_seeder.py | def _seed_all_on_conn | 函数 | conn | 内联 seed — 完全独立不依赖 IcebergSchemaSeeder 类 |
| iceberg_schema_seeder.py | def main | 函数 |  |  |
| iceberg_slang_substituti | def ensure_tables | 函数 | db | 建表 + 种子数据 + B方案: AI生成词默认 disabled=0 + 90 |
| iceberg_slang_substituti | def load_active_map | 函数 | db | 加载所有 enabled=1 的词表 -> dict |
| iceberg_slang_substituti | def substitute | 函数 | text, slang_map, db | 核心替换函数 — 正则一次性替换, 不会二次替换产物里的文字.

之前用逐个 r |
| iceberg_slang_substituti | def q5_generate_slang | 函数 | seed_words | 让 Q5 根据种子词联想更多平替黑话.
输入: ["警察", "报警", ... |
| iceberg_slang_substituti | def discover_from_q5 | 函数 | db | Q5 自动发现新平替 — 补充种子词覆盖不足的领域 |
| iceberg_slang_substituti | def add_slang_pair | 函数 | db, orig, sub, cat |  |
| iceberg_slang_substituti | def discover_from_bilibili | 函数 | db | 从 B 站热门视频评论区抓平替词 (bilibili-api 公开接口) |
| iceberg_slang_substituti | def register_routes | 函数 | app | 注册 Flask 路由 + 输入层 before_request + 输出层 a |
| iceberg_slang_substituti | def run_once | 函数 |  | 跑一轮: Q5 造词 + B站发现 + 词表统计 |
| iceberg_slang_substituti | def daemon | 函数 |  | 每 30 分钟跑一轮 |
| iceberg_bridge.py | def ts_to_iceberg_lang | 函数 | ts_lang | translation_studio lang → 冰山 lang. |
| iceberg_bridge.py | def iceberg_to_ts_lang | 函数 | ice_lang | 冰山 lang → translation_studio lang. |
| iceberg_bridge.py | def generate_content_key | 函数 | domain, original_text, categor | 从原文生成确定性 content_key (基于 hash). |
| iceberg_bridge.py | def publish_to_iceberg | 函数 | translations, domain, content_ | 把 translation_studio 的四语言译文注入冰山 content_ |
| iceberg_bridge.py | def batch_publish_to_iceberg | 函数 | tasks, domain | 批量 publish: 适合从 mt_trans_tasks 读取已完成任务后集 |
| iceberg_bridge.py | def auto_translate_and_publi | 函数 | source_text, source_lang, targ | 🔥 全流程: 原文 → 自动翻到四语言 → 注入冰山 content_matri |
| iceberg_meta_routes.py | def _db | 函数 |  |  |
| iceberg_meta_routes.py | def _now | 函数 |  |  |
| iceberg_meta_routes.py | def _audit | 函数 | action, target, detail, userna | 所有管理操作自动落审计 (mt_iceberg_admin_audit) |
| iceberg_meta_routes.py | def _ensure_admin_tables | 函数 |  |  |
| iceberg_meta_routes.py | def api_pulse | 函数 |  |  |
| iceberg_meta_routes.py | def api_domains | 函数 |  |  |
| iceberg_meta_routes.py | def api_domain_detail | 函数 | domain_key |  |
| iceberg_meta_routes.py | def api_self | 函数 |  |  |
| iceberg_meta_routes.py | def api_matrix | 函数 |  |  |
| iceberg_meta_routes.py | def api_runs | 函数 |  |  |
| iceberg_meta_routes.py | def api_thresholds | 函数 |  |  |
| iceberg_meta_routes.py | def api_optimizations | 函数 |  |  |
| iceberg_meta_routes.py | def api_daemons | 函数 |  | 五自相关 daemon 的心跳状态 (读 mt_daemon_registry) |
| iceberg_meta_routes.py | def api_audit | 函数 |  |  |
| iceberg_meta_routes.py | def api_thresholds_update | 函数 |  | body: {"brain_upgrade": 600, "health_str |
| iceberg_meta_routes.py | def api_binding_toggle | 函数 | domain_key, self_key | body: {"enabled": false, "reason": "临时停用 |
| iceberg_meta_routes.py | def api_evolve | 函数 | self_key | 手动触发某自能力 — 跑意识脉冲 + 调用对应 daemon 入口 (若可调用) |
| iceberg_meta_routes.py | def api_domain_health | 函数 |  | 手动覆盖某域健康分 body: {"domain": "education",  |
| iceberg_meta_routes.py | def api_run_delete | 函数 | run_id |  |
| iceberg_meta_routes.py | def iceberg_center | 函数 |  |  |
| mobile_iceberg_routes.py | def _db | 函数 |  |  |
| mobile_iceberg_routes.py | def c | 函数 | db, q |  |
| mobile_iceberg_routes.py | def _f | 函数 | n | 大数格式化 |
| mobile_iceberg_routes.py | def page_mobile | 函数 |  | 🧊 冰山移动管理端页面 |
| mobile_iceberg_routes.py | def api_mobile_status | 函数 |  | 聚合返回冰山核心状态 |
| mobile_iceberg_routes.py | def api_new_directions | 函数 |  | 自发明方向列表 |
| mobile_iceberg_routes.py | def api_daemon_status | 函数 |  | 两个关键 daemon 是否在跑 |
| mobile_iceberg_routes.py | def api_empower_mobile | 函数 |  | 赋能状态 (移动端轻量) |
| mobile_iceberg_routes.py | def api_ble_devices | 函数 |  | 已扫描的 BLE 设备清单 (Flask DB 历史) |
| mobile_iceberg_routes.py | def api_ble_gatt | 函数 | addr | 单台设备的 GATT 缓存详情 |
| mobile_iceberg_routes.py | def api_ble_arduino | 函数 |  | Arduino 已检测设备 |
| mobile_iceberg_routes.py | def api_admin_daemons | 函数 |  | daemon 注册表 + 运行状态 (smart_mount_processes |
| mobile_iceberg_routes.py | def api_admin_health | 函数 |  | 系统健康快照 |
| mobile_iceberg_routes.py | def api_admin_actions | 函数 |  | 管理员操作: restart_daemon / stop_daemon / pi |
| mobile_iceberg_routes.py | def apk_landing | 函数 |  | 📱 APK 下载引导页 (小米 13 / 所有手机) |
| mobile_iceberg_routes.py | def serve_apk_binary | 函数 |  | 真正的 APK 二进制下载 — send_from_directory 绕过拦截 |
<!-- AUTO-GENERATED-END:functions -->

## 6. 依赖关系
<!-- AUTO-GENERATED-START:deps -->
- 冰山 ← 古灵阁 (通过 mt_collab_bus_events 接收交易裁决广播)
- 冰山 → 仙女座 (触发 autopilot_v2 S5 广播,驱动仙女座进化)
- 冰山 ← 仙女座 (andromeda_workflow_engine 的自我修正回写)
- 冰山 → mt_iceberg_consciousness_runs (意识脉冲留痕)
- 冰山 → mt_ai_brain_feed_log (脑库投喂)
**扫描统计**: 23 模块 | 28 表 | 47 路由
<!-- AUTO-GENERATED-END:deps -->
