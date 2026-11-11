# MTSCOS Flask API 总览

> 自动生成时间: 2026-11-12 06:39
> 共 **470** 个端点,按 Blueprint 分组

## Blueprint: `andromeda_hub_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /andromeda/hub | andromeda_hub_page | 仙女座 Andromeda |
| ANY | /api/andromeda/hub | api_andromeda_hub | 仙女座 Andromeda |

_2 个端点_

## Blueprint: `andromeda_openai_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /v1/chat/completions | chat_completions | 仙女座 Andromeda |
| ANY | /v1/models | list_models | 仙女座 Andromeda |
| ANY | /v1/responses | responses | 仙女座 Andromeda |

_3 个端点_

## Blueprint: `andromeda_stats_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /andromeda/stats | stats_page | 仙女座 Andromeda |
| ANY | /api/andromeda/stats/dispatch | stats_dispatch | 仙女座 Andromeda |
| ANY | /api/andromeda/stats/events | stats_events | 仙女座 Andromeda |
| ANY | /api/andromeda/stats/overview | stats_overview | 仙女座 Andromeda |

_4 个端点_

## Blueprint: `app`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | / | get_data | 仙女座 Andromeda |
| ANY | /_rules/bypass_approve | api_rules_bypass_approve | top-level |
| ANY | /_rules/bypass_request | api_rules_bypass_submit | top-level |
| ANY | /_rules/check | api_rules_check_frontend | top-level |
| ANY | /_rules/config_value/<key> | api_get_config_value | top-level |
| ANY | /_rules/grace_windows | api_get_grace_windows | top-level |
| ANY | /_rules/proposals | api_get_rule_proposals | top-level |
| ANY | /_rules/proposals/<pid>/ai_review | api_ai_review_rule_propo | top-level |
| ANY | /_rules/proposals/<pid>/approve | api_approve_rule_proposa | top-level |
| ANY | /_rules/proposals/<pid>/final_approve | api_final_approve_rule_p | top-level |
| ANY | /_rules/proposals/<pid>/withdraw | api_withdraw_rule_propos | top-level |
| ANY | /_rules/red_lines | api_get_red_lines | top-level |
| ANY | /_rules/report_event | api_rules_report_event | top-level |
| ANY | /_rules/simulate | api_rules_simulate | top-level |
| ANY | /_ui/report_particle_perf | api_report_particle_perf | top-level |
| ANY | /_ui/report_ui_event | api_report_ui_event | top-level |
| ANY | /_ui/site_decoration | api_get_site_decoration | top-level |
| ANY | /admin_app/ | _mt_admin_app_catchall | top-level |
| ANY | /admin_app/<path:name> | _mt_admin_app_catchall | top-level |
| ANY | /admin_app/neural_hub_dashboard | neural_hub_dashboard_pag | top-level |
| ANY | /andromeda | run | 仙女座 Andromeda |
| ANY | /api/andromeda/stars | api_andromeda_stars | top-level |
| ANY | /api/andromeda/stars/<domain> | api_andromeda_star_by_do | top-level |
| ANY | /api/andromeda/state | api_andromeda_state | top-level |
| ANY | /api/arduino/auto_detect | api_arduino_auto_detect | top-level |
| ANY | /api/center-node/directions | api_center_node_directio | top-level |
| ANY | /api/center-node/heartbeat | api_center_node_heartbea | top-level |
| ANY | /api/center-node/log-batch | api_center_node_log_batc | top-level |
| ANY | /api/center-node/register | api_center_node_register | top-level |
| ANY | /api/client/init | api_client_init | top-level |
| ANY | /api/client/verify_keys | api_client_verify_keys | top-level |
| ANY | /api/console/record | _record_console_error | top-level |
| ANY | /api/console/run_cycle | _trigger_console_run_cyc | top-level |
| ANY | /api/container/heartbeat | api_mt_container_heartbe | top-level |
| ANY | /api/container/status | api_mt_container_status | top-level |
| ANY | /api/data | get_data | 仙女座 Andromeda |
| ANY | /api/dev_flow/<flow_id> | api_dev_flow_advance | top-level |
| ANY | /api/dev_flow/<flow_id>/advance | api_dev_flow_advance | top-level |
| ANY | /api/dev_flow/<flow_id>/git_sync | api_dev_flow_git_sync_ap | top-level |
| ANY | /api/dev_flow/<flow_id>/test1000 | api_dev_flow_test1000 | top-level |
| ANY | /api/dev_flow/<flow_id>/version_upgrade | api_dev_flow_version_upg | top-level |
| ANY | /api/dev_flow/create | api_dev_flow_create | top-level |
| ANY | /api/dev_flow/list | api_dev_flow_list | top-level |
| ANY | /api/diag/sa_dual | _mt_diag_sa_dual | top-level |
| ANY | /api/diag/sa_dual/force_sa | _mt_diag_force_sa | top-level |
| ANY | /api/employees | api_employees | 仙女座 Andromeda |
| ANY | /api/hardware/dual-status | api_hardware_dual_status | top-level |
| ANY | /api/health | health | top-level |
| ANY | /api/homepage/stats | api_homepage_stats | top-level |
| ANY | /api/neuralhub/api_docs | api_neuralhub_api_docs | top-level |
| ANY | /api/neuralhub/arduino_compile_assist | api_arduino_compile_assi | top-level |
| ANY | /api/neuralhub/bili_extract | api_neuralhub_bili_extra | top-level |
| ANY | /api/neuralhub/bootstrap | api_neuralhub_bootstrap | top-level |
| ANY | /api/neuralhub/call | api_neuralhub_call | top-level |
| ANY | /api/neuralhub/daemon_status | api_neuralhub_daemon_sta | top-level |
| ANY | /api/neuralhub/daemon_tick | api_neuralhub_daemon_tic | top-level |
| ANY | /api/neuralhub/edu_reform_check | api_neuralhub_edu_reform | top-level |
| ANY | /api/neuralhub/edu_reform_feed | api_neuralhub_edu_reform | top-level |
| ANY | /api/neuralhub/employee_distribution | api_neuralhub_employee_d | top-level |
| ANY | /api/neuralhub/evolution_logs | api_neuralhub_evolution_ | top-level |
| ANY | /api/neuralhub/knowledge_feed | api_neuralhub_knowledge_ | top-level |
| ANY | /api/neuralhub/knowledge_inventory | api_neuralhub_knowledge_ | top-level |
| ANY | /api/neuralhub/models | api_neuralhub_models | top-level |
| ANY | /api/neuralhub/prompt_versions | api_neuralhub_prompt_ver | top-level |
| ANY | /api/neuralhub/rebalance | api_neuralhub_rebalance | top-level |
| ANY | /api/neuralhub/rollback | api_neuralhub_rollback | top-level |
| ANY | /api/neuralhub/route_register | api_neuralhub_route_regi | top-level |
| ANY | /api/neuralhub/routes | api_neuralhub_routes | top-level |
| ANY | /api/neuralhub/routes/<task_name> | api_neuralhub_delete_rou | top-level |
| ANY | /api/neuralhub/self_upgrade_cycle | api_neuralhub_self_upgra | top-level |
| ANY | /api/neuralhub/stats | api_neuralhub_stats | top-level |
| ANY | /api/neuralhub/system_info | api_neuralhub_system_inf | top-level |
| ANY | /api/security-brigade/gate | api_security_brigade_gat | top-level |
| ANY | /api/sync/push | api_sync_push | 仙女座 Andromeda |
| ANY | /api/sync/refresh | api_sync_refresh | 仙女座 Andromeda |
| ANY | /api/system/ping | api_system_ping | top-level |
| ANY | /api/theme/get | api_get_theme | top-level |
| ANY | /api/theme/presets | api_get_theme_presets | top-level |
| ANY | /api/theme/recommend | api_recommend_theme | top-level |
| ANY | /api/theme/reset | api_reset_theme | top-level |
| ANY | /api/theme/reset_custom | api_reset_custom_theme | top-level |
| ANY | /api/theme/set | api_set_theme | top-level |
| ANY | /api/theme/sunrise_sunset | api_get_sunrise_sunset | top-level |
| ANY | /api/user/theme_preferences | api_get_user_theme_prefe | top-level |
| ANY | /apple-touch-icon-precomposed.png | _site_apple_touch_icon | top-level |
| ANY | /apple-touch-icon.png | _site_apple_touch_icon | top-level |
| ANY | /assets/<path:filename> | _serve_assets | top-level |
| ANY | /auth/check_password | check_password | top-level |
| ANY | /auth/check_username | check_username | top-level |
| ANY | /auth/gobelin | login | top-level |
| ANY | /auth/iceberg | login | top-level |
| ANY | /auth/login | login | top-level |
| ANY | /auth/validate | auth_validate | top-level |
| ANY | /favicon.ico | _site_favicon | top-level |
| ANY | /governance/channel/<channel_code> | _mt_channel_detail | top-level |
| ANY | /health | _site_health | top-level |
| ANY | /iceberg | _mt_iceberg_entry | top-level |
| ANY | /index | index | top-level |
| ANY | /manifest.json | _site_manifest | top-level |
| ANY | /sa/dashboard | sa_dashboard | top-level |
| ANY | /sa/verify | sa_remote_verify_page | top-level |
| ANY | /site-icon.svg | _site_icon_svg | top-level |
| ANY | /sitemap.xml | _site_sitemap | top-level |
| ANY | /static/fontawesome/all.min.css | _serve_fa_all_css | top-level |
| ANY | /static/fontawesome/webfonts/<path:filename> | _serve_fa_webfonts | top-level |
| ANY | /stock | _mt_stock_entry | top-level |
| POST | /api/internal/heartbeat | api_internal_heartbeat | top-level |

_107 个端点_

## Blueprint: `auth_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /register |  | 仙女座 Andromeda |

_1 个端点_

## Blueprint: `bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /api/andromeda_daemon_status | api_andromeda_daemon_sta | 仙女座 Andromeda |
| ANY | /api/copy_archive | api_copy_archive | 仙女座 Andromeda |
| ANY | /api/daemon_status | api_daemon_status | 仙女座 Andromeda |
| ANY | /api/db_metrics | api_db_metrics | 仙女座 Andromeda |
| ANY | /api/evolution_timeline | api_evolution_timeline | 仙女座 Andromeda |
| ANY | /api/iceberg/eigenflux | api_eigenflux | 仙女座 Andromeda |
| ANY | /api/iceberg/health | api_iceberg_health | 仙女座 Andromeda |
| ANY | /api/iceberg/upgrade_board | api_upgrade_board | 仙女座 Andromeda |
| ANY | /api/iceberg_layer_stats | api_iceberg_layer_stats | 仙女座 Andromeda |
| ANY | /api/iceberg_structure | api_iceberg_structure | 仙女座 Andromeda |
| ANY | /api/iol_summary | api_iol_summary | 仙女座 Andromeda |
| ANY | /api/knowledge_brain/ask | api_knowledge_ask | 仙女座 Andromeda |
| ANY | /api/knowledge_brain/personas | api_knowledge_personas | 仙女座 Andromeda |
| ANY | /api/knowledge_brain/search | api_knowledge_search | 仙女座 Andromeda |
| ANY | /api/knowledge_brain/semantic | api_knowledge_semantic | 仙女座 Andromeda |
| ANY | /api/knowledge_brain/stats | api_knowledge_stats | 仙女座 Andromeda |
| ANY | /api/knowledge_graph/data | api_knowledge_graph_data | 仙女座 Andromeda |
| ANY | /api/param/changelog | api_param_changelog | 仙女座 Andromeda |
| ANY | /api/param/delete | api_param_delete | 仙女座 Andromeda |
| ANY | /api/param/list | api_param_list | 仙女座 Andromeda |
| ANY | /api/param/scan | api_param_scan | 仙女座 Andromeda |
| ANY | /api/param/set | api_param_set | 仙女座 Andromeda |
| ANY | /api/param/stats | api_param_stats | 仙女座 Andromeda |
| ANY | /api/persona_chat | api_persona_chat | 仙女座 Andromeda |
| ANY | /api/persona_chat/history | api_persona_chat_history | 仙女座 Andromeda |
| ANY | /api/system_health | api_system_health | 仙女座 Andromeda |
| ANY | /api/twin_machine | api_twin_machine | 仙女座 Andromeda |
| ANY | /api/upgrade_overviews | api_upgrade_overviews | 仙女座 Andromeda |
| ANY | /api/upgrade_reports | api_upgrade_reports | 仙女座 Andromeda |
| ANY | /api/wqx/generate | api_wqx_generate | 仙女座 Andromeda |
| ANY | /api/wqx/list | api_wqx_list | 仙女座 Andromeda |
| ANY | /api/wqx/task/<task_id> | api_wqx_task | 仙女座 Andromeda |
| ANY | /collapse_theorem | collapse_theorem_page | 仙女座 Andromeda |
| ANY | /dashboard | dashboard_page | 仙女座 Andromeda |
| ANY | /eigenflux_council | eigenflux_council_page | 仙女座 Andromeda |
| ANY | /gray_center | gray_center_page | 仙女座 Andromeda |
| ANY | /health_board | health_board_page | 仙女座 Andromeda |
| ANY | /iceberg_center | iceberg_center_page | 仙女座 Andromeda |
| ANY | /iceberg_evolution | iceberg_evolution_page | 仙女座 Andromeda |
| ANY | /iceberg_meta | iceberg_meta_page | 仙女座 Andromeda |
| ANY | /knowledge_brain | knowledge_brain_page | 仙女座 Andromeda |
| ANY | /knowledge_graph | knowledge_graph_page | 仙女座 Andromeda |
| ANY | /param_center | param_center_page | 仙女座 Andromeda |
| ANY | /persona_chat | persona_chat_page | 仙女座 Andromeda |
| ANY | /stats/overview | stats_overview | 仙女座 Andromeda |
| ANY | /upgrade_board | upgrade_board_page | 仙女座 Andromeda |
| ANY | /wenquxing | wenquxing_page | 仙女座 Andromeda |

_47 个端点_

## Blueprint: `chat_plus_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /api/local-chat/jump/center | chat_jump_center | 仙女座 Andromeda |
| ANY | /api/local-chat/jump/resolve | chat_jump_resolve | 仙女座 Andromeda |
| ANY | /api/local-chat/jump/task/<int:task_id> | chat_jump_task | 仙女座 Andromeda |
| ANY | /api/local-chat/jump/team | chat_jump_team | 仙女座 Andromeda |
| ANY | /api/local-chat/mention | chat_mention | 仙女座 Andromeda |
| ANY | /api/local-chat/msg/<int:mid> | chat_msg_edit | 仙女座 Andromeda |
| ANY | /api/local-chat/msg/<int:mid>/feedback | chat_msg_feedback | 仙女座 Andromeda |
| ANY | /api/local-chat/msg/context | chat_msg_context | 仙女座 Andromeda |
| ANY | /api/local-chat/msg/list | chat_msg_list | 仙女座 Andromeda |
| ANY | /api/local-chat/multi-ai | chat_multi_ai | 仙女座 Andromeda |
| ANY | /api/local-chat/plus/meta | chat_plus_meta | 仙女座 Andromeda |
| ANY | /api/local-chat/search | chat_search | 仙女座 Andromeda |
| ANY | /api/local-chat/session/<sid>/archive | chat_session_archive | 仙女座 Andromeda |
| ANY | /api/local-chat/session/<sid>/export | chat_export | 仙女座 Andromeda |
| ANY | /api/local-chat/session/<sid>/read | chat_mark_read | 仙女座 Andromeda |
| ANY | /api/local-chat/unread | chat_unread | 仙女座 Andromeda |

_16 个端点_

## Blueprint: `collab_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /events | api_bus_events | 仙女座 Andromeda |
| ANY | /publish | api_publish | 仙女座 Andromeda |
| ANY | /radar/cache | api_radar_cache | 仙女座 Andromeda |
| ANY | /start | api_start | 仙女座 Andromeda |
| ANY | /status | api_bus_status | 仙女座 Andromeda |
| ANY | /subscribers | api_subscribers | 仙女座 Andromeda |

_6 个端点_

## Blueprint: `collab_bus_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /events | api_events | 仙女座 Andromeda |
| ANY | /publish | api_publish | 仙女座 Andromeda |
| ANY | /radar/cache | api_radar_cache | 仙女座 Andromeda |
| ANY | /start | api_start_radar | 仙女座 Andromeda |
| ANY | /status | api_status | 仙女座 Andromeda |
| ANY | /subscribers | api_subscribers | 仙女座 Andromeda |
| ANY | /version/bump | api_version_bump | 仙女座 Andromeda |
| ANY | /version/components | api_version_components | 仙女座 Andromeda |
| ANY | /version/history | api_version_history | 仙女座 Andromeda |

_9 个端点_

## Blueprint: `collab_rd_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /dashboard/feedback | api_dashboard_feedback | 仙女座 Andromeda |
| ANY | /dashboard/health | api_dashboard_health | 仙女座 Andromeda |
| ANY | /dashboard/network-graph | api_dashboard_network_gr | 仙女座 Andromeda |
| ANY | /dashboard/overview | api_dashboard_overview | 仙女座 Andromeda |
| ANY | /dashboard/rd-pipeline | api_dashboard_rd_pipelin | 仙女座 Andromeda |
| ANY | /hub-network | api_hub_network | 仙女座 Andromeda |
| ANY | /network | api_network | 仙女座 Andromeda |
| ANY | /pact | api_pacts | 仙女座 Andromeda |
| ANY | /pacts | api_pacts | 仙女座 Andromeda |
| ANY | /rd/compose | api_rd_compose | 仙女座 Andromeda |
| ANY | /rd/derivatives | api_rd_derivatives | 仙女座 Andromeda |
| ANY | /rd/derive | api_rd_derive | 仙女座 Andromeda |
| ANY | /rd/feedback | api_rd_feedback | 仙女座 Andromeda |
| ANY | /rd/full-cycle | api_rd_full_cycle | 仙女座 Andromeda |
| ANY | /rd/pipeline | api_rd_pipeline | 仙女座 Andromeda |
| ANY | /rd/sprint | api_rd_sprint | 仙女座 Andromeda |
| ANY | /rebuild | api_rebuild | 仙女座 Andromeda |
| ANY | /suggest | api_suggest | 仙女座 Andromeda |

_18 个端点_

## Blueprint: `daemon_skill_lab_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /api/daemon-lab/audit | lab_audit_query | top-level |
| ANY | /api/daemon-lab/auto-claim | lab_auto_claim | top-level |
| ANY | /api/daemon-lab/hall/accept | hall_accept | top-level |
| ANY | /api/daemon-lab/hall/approve | hall_approve | top-level |
| ANY | /api/daemon-lab/hall/archive | hall_archive | top-level |
| ANY | /api/daemon-lab/hall/auto-work | hall_auto_work | top-level |
| ANY | /api/daemon-lab/hall/board | hall_board | top-level |
| ANY | /api/daemon-lab/hall/cancel | hall_cancel | top-level |
| ANY | /api/daemon-lab/hall/center-delegate | hall_center_delegate | top-level |
| ANY | /api/daemon-lab/hall/claim | hall_claim | top-level |
| ANY | /api/daemon-lab/hall/deliver | hall_deliver | top-level |
| ANY | /api/daemon-lab/hall/pipeline | hall_pipeline | top-level |
| ANY | /api/daemon-lab/hall/progress | hall_progress | top-level |
| ANY | /api/daemon-lab/hall/proposal | hall_proposal | top-level |
| ANY | /api/daemon-lab/hall/publish-meta | hall_publish_meta | top-level |
| ANY | /api/daemon-lab/hall/recycle | hall_recycle_api | top-level |
| ANY | /api/daemon-lab/hall/residents | hall_residents | top-level |
| ANY | /api/daemon-lab/hall/smart-dispatch | hall_smart_dispatch | top-level |
| ANY | /api/daemon-lab/hall/start | hall_start | top-level |
| ANY | /api/daemon-lab/hall/submit | hall_submit | top-level |
| ANY | /api/daemon-lab/hall/task | hall_task_detail | top-level |
| ANY | /api/daemon-lab/hr/roster | hr_roster | top-level |
| ANY | /api/daemon-lab/overview | lab_overview | top-level |
| ANY | /api/daemon-lab/test/auto-team | auto_team_api | top-level |
| ANY | /api/daemon-lab/test/derive-skill | derive_skill | top-level |
| ANY | /api/daemon-lab/test/form-roster | form_test_roster | top-level |
| ANY | /api/daemon-lab/test/frontline-patrol | frontline_patrol_api | top-level |
| ANY | /api/daemon-lab/test/gold-team/auto | gold_team_auto | top-level |
| ANY | /api/daemon-lab/test/gold-team/claim | gold_team_claim | top-level |
| ANY | /api/daemon-lab/test/spawn-ai | spawn_ai_api | top-level |
| ANY | /api/daemon-lab/workspaces | lab_workspaces | top-level |
| ANY | /daemon-skill-lab | lab_page | top-level |

_32 个端点_

## Blueprint: `eigenflux_arduino_advanced_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /read_serial | read_serial | 仙女座 Andromeda |
| ANY | /scan_ports | scan_ports | 仙女座 Andromeda |
| ANY | /start_monitoring | start_monitoring | 仙女座 Andromeda |
| ANY | /stop_monitoring | stop_monitoring | 仙女座 Andromeda |

_4 个端点_

## Blueprint: `eigenflux_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /center_stats | center_stats | 仙女座 Andromeda |
| ANY | /experts | experts | 仙女座 Andromeda |
| ANY | /messages | messages | 仙女座 Andromeda |
| ANY | /tasks | tasks | 仙女座 Andromeda |
| ANY | /teams | teams | 仙女座 Andromeda |

_5 个端点_

## Blueprint: `eigenflux_self_healing_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /scan_all | scan_all | 仙女座 Andromeda |
| ANY | /scan_broken_templates | scan_broken_templates | 仙女座 Andromeda |
| ANY | /scan_db_integrity | scan_db_integrity | 仙女座 Andromeda |
| ANY | /scan_disk_space | scan_disk_space | 仙女座 Andromeda |
| ANY | /scan_empty_files | scan_empty_files | 仙女座 Andromeda |
| ANY | /scan_import_errors | scan_import_errors | 仙女座 Andromeda |
| ANY | /scan_large_logs | scan_large_logs | 仙女座 Andromeda |
| ANY | /scan_log_errors | scan_log_errors | 仙女座 Andromeda |
| ANY | /scan_missing_indexes | scan_missing_indexes | 仙女座 Andromeda |
| ANY | /scan_missing_init | scan_missing_init | 仙女座 Andromeda |
| ANY | /scan_pyc_files | scan_pyc_files | 仙女座 Andromeda |
| ANY | /scan_pycache | scan_pycache | 仙女座 Andromeda |
| ANY | /scan_stale_sessions | scan_stale_sessions | 仙女座 Andromeda |
| ANY | /scan_syntax_errors | scan_syntax_errors | 仙女座 Andromeda |
| ANY | /scan_temp_files | scan_temp_files | 仙女座 Andromeda |

_15 个端点_

## Blueprint: `gobelin_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /account | account_refresh | 古灵阁 Gobelin |
| ANY | /account/refresh | account_refresh | 古灵阁 Gobelin |
| ANY | /api/gobelin/daemons | gobelin_daemons | 古灵阁 Gobelin |
| ANY | /api/gobelin/status | gobelin_status | 古灵阁 Gobelin |
| ANY | /api/gobelin/status-v2 | api_gobelin_status_v2 | 古灵阁 Gobelin |
| ANY | /api/gobelin/subsystem/<key> | api_gobelin_subsystem | 古灵阁 Gobelin |
| ANY | /api/gobelin/system | api_gobelin_system | 古灵阁 Gobelin |
| ANY | /autonomous/cycle | autonomous_cycle | 古灵阁 Gobelin |
| ANY | /autonomous/execute | autonomous_execute | 古灵阁 Gobelin |
| ANY | /autonomous/report | autonomous_report | 古灵阁 Gobelin |
| ANY | /autonomous/scan | autonomous_scan | 古灵阁 Gobelin |
| ANY | /collab/analyze/<int:proposal_id> | collab_analyze | 古灵阁 Gobelin |
| ANY | /collab/dispatch/<int:proposal_id> | collab_dispatch | 古灵阁 Gobelin |
| ANY | /collab/growth | collab_growth | 古灵阁 Gobelin |
| ANY | /collab/minutes/<int:plan_id> | collab_minutes | 古灵阁 Gobelin |
| ANY | /collab/proposal/<int:proposal_id> | collab_proposal | 古灵阁 Gobelin |
| ANY | /collab/run-pending | collab_run_pending | 古灵阁 Gobelin |
| ANY | /collab/traces | collab_traces | 古灵阁 Gobelin |
| ANY | /community/bootstrap | community_bootstrap | 古灵阁 Gobelin |
| ANY | /community/calibrations | community_calibrations | 古灵阁 Gobelin |
| ANY | /community/employees | community_employees | 古灵阁 Gobelin |
| ANY | /community/health | community_health | 古灵阁 Gobelin |
| ANY | /community/roles | community_roles | 古灵阁 Gobelin |
| ANY | /community/training | community_training | 古灵阁 Gobelin |
| ANY | /compliance | compliance_audit | 古灵阁 Gobelin |
| ANY | /dashboard | dashboard_snapshot | 古灵阁 Gobelin |
| ANY | /health | health | 古灵阁 Gobelin |
| ANY | /parliament/proposal/<int:proposal_id> | parliament_proposal | 古灵阁 Gobelin |
| ANY | /parliament/session/<int:session_id> | parliament_session | 古灵阁 Gobelin |
| ANY | /parliament/vote-all | parliament_vote_all | 古灵阁 Gobelin |
| ANY | /parliament/vote/<int:proposal_id> | parliament_vote | 古灵阁 Gobelin |
| ANY | /positions | positions_list | 古灵阁 Gobelin |
| ANY | /proposal/create | proposal_create | 古灵阁 Gobelin |
| ANY | /proposals | proposals_list | 古灵阁 Gobelin |
| ANY | /scheduler | scheduler_status | 古灵阁 Gobelin |
| ANY | /seal/<int:proposal_id> | seal_by_proposal | 古灵阁 Gobelin |
| ANY | /seal/audit | seal_audit | 古灵阁 Gobelin |
| ANY | /seal/auto-grant | seal_auto_grant | 古灵阁 Gobelin |
| ANY | /seal/consume | seal_consume | 古灵阁 Gobelin |
| ANY | /seal/request | seal_request | 古灵阁 Gobelin |
| ANY | /seal/status | seal_status | 古灵阁 Gobelin |
| ANY | /seal/verify | seal_verify | 古灵阁 Gobelin |
| ANY | /trades | trades_list | 古灵阁 Gobelin |
| ANY | /view | gobelin_view | 古灵阁 Gobelin |

_44 个端点_

## Blueprint: `gobelin_music_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /<int:pid> | get_project | 古灵阁 Gobelin |
| ANY | /generate | generate | 古灵阁 Gobelin |
| ANY | /genres | list_genres | 古灵阁 Gobelin |
| ANY | /health | health | 古灵阁 Gobelin |
| ANY | /projects | list_projects | 古灵阁 Gobelin |

_5 个端点_

## Blueprint: `gobelin_video_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /<int:pid> | get_project | 古灵阁 Gobelin |
| ANY | /<int:pid>/shots.json | export_shots | 古灵阁 Gobelin |
| ANY | /formats | list_formats | 古灵阁 Gobelin |
| ANY | /generate | generate | 古灵阁 Gobelin |
| ANY | /health | health | 古灵阁 Gobelin |
| ANY | /projects | list_projects | 古灵阁 Gobelin |

_6 个端点_

## Blueprint: `gobelin_writing_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /<int:pid> | api_writing_revise | 古灵阁 Gobelin |
| ANY | /<int:pid>/export/<fmt> | api_writing_export | 古灵阁 Gobelin |
| ANY | /<int:pid>/revise | api_writing_revise | 古灵阁 Gobelin |
| ANY | /create | api_writing_create | 古灵阁 Gobelin |
| ANY | /generate | api_writing_generate | 古灵阁 Gobelin |
| ANY | /genres | api_writing_genres | 古灵阁 Gobelin |
| ANY | /models | api_writing_models | 古灵阁 Gobelin |
| ANY | /params | api_writing_params | 古灵阁 Gobelin |
| ANY | /projects | api_writing_projects | 古灵阁 Gobelin |

_9 个端点_

## Blueprint: `iceberg_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /api/iceberg/achievements | list_achievements | 冰山 Iceberg |
| ANY | /api/iceberg/audit | api_audit | 冰山 Iceberg |
| ANY | /api/iceberg/badges | list_badges | 冰山 Iceberg |
| ANY | /api/iceberg/badges/<category> | list_badges_by_category | 冰山 Iceberg |
| ANY | /api/iceberg/badges/check | check_badges | 冰山 Iceberg |
| ANY | /api/iceberg/bindings/<domain_key>/<self_key>/togg | api_binding_toggle | 冰山 Iceberg |
| ANY | /api/iceberg/daemons | api_daemons | 冰山 Iceberg |
| ANY | /api/iceberg/domain_health | api_domain_health | 冰山 Iceberg |
| ANY | /api/iceberg/domains | api_domains | 冰山 Iceberg |
| ANY | /api/iceberg/domains/<domain_key> | api_domain_detail | 冰山 Iceberg |
| ANY | /api/iceberg/employees | list_employees | 冰山 Iceberg |
| ANY | /api/iceberg/employees/<employee_id> | get_employee | 冰山 Iceberg |
| ANY | /api/iceberg/employees/<employee_id>/chat | get_employee_chat | 冰山 Iceberg |
| ANY | /api/iceberg/evolve/<self_key> | api_evolve | 冰山 Iceberg |
| ANY | /api/iceberg/health | iceberg_health | 冰山 Iceberg |
| ANY | /api/iceberg/lang/grammar/practice | grammar_practice | 冰山 Iceberg |
| ANY | /api/iceberg/lang/sessions | list_lang_sessions | 冰山 Iceberg |
| ANY | /api/iceberg/lang/vocab/due | vocab_due | 冰山 Iceberg |
| ANY | /api/iceberg/matrix | api_matrix | 冰山 Iceberg |
| ANY | /api/iceberg/optimizations | api_optimizations | 冰山 Iceberg |
| ANY | /api/iceberg/pulse | api_pulse | 冰山 Iceberg |
| ANY | /api/iceberg/qbank/exam/generate | generate_exam | 冰山 Iceberg |
| ANY | /api/iceberg/qbank/kps | list_kps | 冰山 Iceberg |
| ANY | /api/iceberg/qbank/questions | list_questions | 冰山 Iceberg |
| ANY | /api/iceberg/qbank/subjects | list_subjects | 冰山 Iceberg |
| ANY | /api/iceberg/qbank/subjects/<subject_id> | get_subject | 冰山 Iceberg |
| ANY | /api/iceberg/runs | api_runs | 冰山 Iceberg |
| ANY | /api/iceberg/runs/<int:run_id> | api_run_delete | 冰山 Iceberg |
| ANY | /api/iceberg/self | api_self | 冰山 Iceberg |
| ANY | /api/iceberg/skills/leaderboard | skill_leaderboard | 冰山 Iceberg |
| ANY | /api/iceberg/skills/usage | list_skill_usage | 冰山 Iceberg |
| ANY | /api/iceberg/thresholds | api_thresholds | 冰山 Iceberg |
| ANY | /iceberg/center | iceberg_center | 冰山 Iceberg |

_33 个端点_

## Blueprint: `mobile_iceberg_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /api/iceberg/admin/actions | api_admin_actions | 冰山 Iceberg |
| ANY | /api/iceberg/admin/daemons | api_admin_daemons | 冰山 Iceberg |
| ANY | /api/iceberg/admin/health | api_admin_health | 冰山 Iceberg |
| ANY | /api/iceberg/ble/arduino | api_ble_arduino | 冰山 Iceberg |
| ANY | /api/iceberg/ble/devices | api_ble_devices | 冰山 Iceberg |
| ANY | /api/iceberg/ble/gatt/<addr> | api_ble_gatt | 冰山 Iceberg |
| ANY | /api/iceberg/daemon_status | api_daemon_status | 冰山 Iceberg |
| ANY | /api/iceberg/empower_mobile | api_empower_mobile | 冰山 Iceberg |
| ANY | /api/iceberg/mobile | api_mobile_status | 冰山 Iceberg |
| ANY | /api/iceberg/new_directions | api_new_directions | 冰山 Iceberg |
| ANY | /apk | apk_landing | 冰山 Iceberg |
| ANY | /apk/binary | serve_apk_binary | 冰山 Iceberg |
| ANY | /apk/download | serve_apk_binary | 冰山 Iceberg |
| ANY | /iceberg/mobile | page_mobile | 冰山 Iceberg |

_14 个端点_

## Blueprint: `sandbox_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /account | api_account | 古灵阁 Gobelin |
| ANY | /ai-agents | api_ai_agents | 古灵阁 Gobelin |
| ANY | /ai-dispatch | api_ai_dispatch | 古灵阁 Gobelin |
| ANY | /audit/close-task | api_audit_close_task | 古灵阁 Gobelin |
| ANY | /audit/ledger | api_audit_ledger | 古灵阁 Gobelin |
| ANY | /audit/logs | api_audit_logs | 古灵阁 Gobelin |
| ANY | /audit/run | api_audit_run | 古灵阁 Gobelin |
| ANY | /audit/task-hall | api_audit_task_hall | 古灵阁 Gobelin |
| ANY | /bank-withdraw | api_bank_withdraw | 古灵阁 Gobelin |
| ANY | /bank-withdrawals | api_bank_withdrawals | 古灵阁 Gobelin |
| ANY | /board-decide-sell | api_board_decide_sell | 古灵阁 Gobelin |
| ANY | /board-lock-profits | api_board_lock_profits | 古灵阁 Gobelin |
| ANY | /data/anomalies | api_data_anomalies | 古灵阁 Gobelin |
| ANY | /data/health | api_data_health | 古灵阁 Gobelin |
| ANY | /decisions | api_decisions | 古灵阁 Gobelin |
| ANY | /deposit-gobelin | api_deposit_gobelin | 古灵阁 Gobelin |
| ANY | /events | api_events | 古灵阁 Gobelin |
| ANY | /execute-sell | api_execute_sell | 古灵阁 Gobelin |
| ANY | /finance-meetings | api_finance_meetings | 古灵阁 Gobelin |
| ANY | /gobelin | api_gobelin | 古灵阁 Gobelin |
| ANY | /intel/recent | api_intel_recent | 古灵阁 Gobelin |
| ANY | /intel/status | api_intel_status | 古灵阁 Gobelin |
| ANY | /kline | api_kline | 古灵阁 Gobelin |
| ANY | /positions | api_positions | 古灵阁 Gobelin |
| ANY | /radar | api_radar | 古灵阁 Gobelin |
| ANY | /review | api_review | 古灵阁 Gobelin |
| ANY | /screen/recent | api_screen_recent | 古灵阁 Gobelin |
| ANY | /screen/status | api_screen_status | 古灵阁 Gobelin |
| ANY | /status | api_status | 古灵阁 Gobelin |
| ANY | /trades | api_trades | 古灵阁 Gobelin |
| ANY | /trades-jsonl | api_trades_jsonl | 古灵阁 Gobelin |
| ANY | /trigger-review | api_trigger_review | 古灵阁 Gobelin |
| ANY | /warden/status | api_warden_status | 古灵阁 Gobelin |

_33 个端点_

## Blueprint: `shield_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /andromeda/feed | andromeda_feed | 古灵阁 Gobelin |
| ANY | /andromeda/ingest | andromeda_ingest | 古灵阁 Gobelin |
| ANY | /audit/check/<dim_code> | audit_single_dim | 古灵阁 Gobelin |
| ANY | /audit/dimensions | audit_dimensions | 古灵阁 Gobelin |
| ANY | /audit/scan | audit_full_scan | 古灵阁 Gobelin |
| ANY | /bus/events | bus_events | 古灵阁 Gobelin |
| ANY | /bus/forces | bus_forces | 古灵阁 Gobelin |
| ANY | /bus/publish | bus_publish | 古灵阁 Gobelin |
| ANY | /centers/status | centers_status | 古灵阁 Gobelin |
| ANY | /comfy/jobs | comfy_jobs | 古灵阁 Gobelin |
| ANY | /comfy/submit | comfy_submit | 古灵阁 Gobelin |
| ANY | /customs/audit | customs_audit | 古灵阁 Gobelin |
| ANY | /customs/check | customs_check | 古灵阁 Gobelin |
| ANY | /customs/status | customs_status | 古灵阁 Gobelin |
| ANY | /iceberg/inject | iceberg_inject | 古灵阁 Gobelin |
| ANY | /iceberg/proposal | iceberg_proposal | 古灵阁 Gobelin |
| ANY | /peacekeeping/status | peacekeeping_status | 古灵阁 Gobelin |
| ANY | /retro/complete | retro_complete | 古灵阁 Gobelin |
| ANY | /sa/audit | sa_audit | 古灵阁 Gobelin |
| ANY | /sa/status | sa_status | 古灵阁 Gobelin |
| ANY | /sa/verify | sa_verify | 古灵阁 Gobelin |
| ANY | /status | shield_status | 古灵阁 Gobelin |

_22 个端点_

## Blueprint: `stock_sandbox_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /daemon/start | api_daemon_start | 古灵阁 Gobelin |
| ANY | /daemon/stop | api_daemon_stop | 古灵阁 Gobelin |
| ANY | /portfolio/<session_id> | api_portfolio_session | 古灵阁 Gobelin |
| ANY | /positions | api_positions | 古灵阁 Gobelin |
| ANY | /reports | api_reports | 古灵阁 Gobelin |
| ANY | /sessions | api_sessions | 古灵阁 Gobelin |
| ANY | /signals | api_signals | 古灵阁 Gobelin |
| ANY | /simulate | api_simulate | 古灵阁 Gobelin |
| ANY | /status | api_status | 古灵阁 Gobelin |
| ANY | /tick | api_tick | 古灵阁 Gobelin |
| ANY | /trades | api_trades | 古灵阁 Gobelin |

_11 个端点_

## Blueprint: `team_collab_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | /api/collab/channel/<int:cid> | collab_channel | 古灵阁 Gobelin |
| ANY | /api/collab/channel/<int:cid>/say | collab_say | 古灵阁 Gobelin |
| ANY | /api/collab/channels | collab_channels | 古灵阁 Gobelin |
| ANY | /api/collab/feed | collab_feed | 古灵阁 Gobelin |
| ANY | /api/collab/overview | collab_overview | 古灵阁 Gobelin |
| ANY | /api/collab/pulse | collab_pulse | 古灵阁 Gobelin |
| ANY | /api/collab/rebuild | collab_rebuild | 古灵阁 Gobelin |

_7 个端点_

## Blueprint: `trading_bp`

| 方法 | URL | 处理函数 | 所属系统 |
|------|-----|----------|----------|
| ANY | / | api_overview | 古灵阁 Gobelin |
| ANY | /api/candidates | api_candidates | 古灵阁 Gobelin |
| ANY | /api/crowd/ollama-health | api_ollama_health | 古灵阁 Gobelin |
| ANY | /api/hall/sync | api_hall_sync | 古灵阁 Gobelin |
| ANY | /api/openclaw/<path:subpath> | api_openclaw_proxy | 古灵阁 Gobelin |
| ANY | /api/openclaw/healthz | api_openclaw_health | 古灵阁 Gobelin |
| ANY | /api/order | api_order | 古灵阁 Gobelin |
| ANY | /api/overview | api_overview | 古灵阁 Gobelin |
| ANY | /api/positions | api_positions | 古灵阁 Gobelin |
| ANY | /api/review/brain-bank | api_review_brain_bank | 古灵阁 Gobelin |
| ANY | /api/review/daily | api_review_daily | 古灵阁 Gobelin |
| ANY | /api/review/weekly | api_review_weekly | 古灵阁 Gobelin |
| ANY | /api/risk-check | api_risk_check | 古灵阁 Gobelin |
| ANY | /api/sandbox-data | api_sandbox_data | 古灵阁 Gobelin |
| ANY | /api/sandbox-order | api_sandbox_order | 古灵阁 Gobelin |
| ANY | /api/sandbox-suggest | api_sandbox_suggest | 古灵阁 Gobelin |
| ANY | /api/suggest | api_suggest | 古灵阁 Gobelin |

_17 个端点_