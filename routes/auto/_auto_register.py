# 自动生成的Blueprint注册代码
# 请将此代码添加到 server_real_db.py 的 Blueprint 注册区域

try:
    from routes.auto_eigenflux_self_healing import eigenflux_self_healing_bp
    app.register_blueprint(eigenflux_self_healing_bp)
except Exception as _e:
    print(f"[WARN] Failed to register eigenflux_self_healing_bp: {_e}")

try:
    from routes.auto_education_supervision_service import education_supervision_service_bp
    app.register_blueprint(education_supervision_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register education_supervision_service_bp: {_e}")

try:
    from routes.auto_school_governance_service import school_governance_service_bp
    app.register_blueprint(school_governance_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register school_governance_service_bp: {_e}")

try:
    from routes.auto_education_ai_application_service import education_ai_application_service_bp
    app.register_blueprint(education_ai_application_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register education_ai_application_service_bp: {_e}")

try:
    from routes.auto_education_personalization_service import education_personalization_service_bp
    app.register_blueprint(education_personalization_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register education_personalization_service_bp: {_e}")

try:
    from routes.auto_education_accreditation_service import education_accreditation_service_bp
    app.register_blueprint(education_accreditation_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register education_accreditation_service_bp: {_e}")

try:
    from routes.auto_education_sustainable_service import education_sustainable_service_bp
    app.register_blueprint(education_sustainable_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register education_sustainable_service_bp: {_e}")

try:
    from routes.auto_educational_information_service import educational_information_service_bp
    app.register_blueprint(educational_information_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register educational_information_service_bp: {_e}")

try:
    from routes.auto_education_special_project_service import education_special_project_service_bp
    app.register_blueprint(education_special_project_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register education_special_project_service_bp: {_e}")

try:
    from routes.auto_education_bci_service import education_bci_service_bp
    app.register_blueprint(education_bci_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register education_bci_service_bp: {_e}")

try:
    from routes.auto_education_smart_customer_service import education_smart_customer_service_bp
    app.register_blueprint(education_smart_customer_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register education_smart_customer_service_bp: {_e}")

try:
    from routes.auto_education_smart_supervision_service import education_smart_supervision_service_bp
    app.register_blueprint(education_smart_supervision_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register education_smart_supervision_service_bp: {_e}")

try:
    from routes.auto_education_data_governance_service import education_data_governance_service_bp
    app.register_blueprint(education_data_governance_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register education_data_governance_service_bp: {_e}")

try:
    from routes.auto_ai_reinforcement_learning import ai_reinforcement_learning_bp
    app.register_blueprint(ai_reinforcement_learning_bp)
except Exception as _e:
    print(f"[WARN] Failed to register ai_reinforcement_learning_bp: {_e}")

try:
    from routes.auto_eigenflux_arduino_advanced import eigenflux_arduino_advanced_bp
    app.register_blueprint(eigenflux_arduino_advanced_bp)
except Exception as _e:
    print(f"[WARN] Failed to register eigenflux_arduino_advanced_bp: {_e}")

try:
    from routes.auto_permission_optimizer_service import permission_optimizer_service_bp
    app.register_blueprint(permission_optimizer_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register permission_optimizer_service_bp: {_e}")

try:
    from routes.auto_student_club_service import student_club_service_bp
    app.register_blueprint(student_club_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register student_club_service_bp: {_e}")

try:
    from routes.auto_education_intelligent_tutoring_service import education_intelligent_tutoring_service_bp
    app.register_blueprint(education_intelligent_tutoring_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register education_intelligent_tutoring_service_bp: {_e}")

try:
    from routes.auto_education_edge_computing_service import education_edge_computing_service_bp
    app.register_blueprint(education_edge_computing_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register education_edge_computing_service_bp: {_e}")

try:
    from routes.auto_education_smart_decision_service import education_smart_decision_service_bp
    app.register_blueprint(education_smart_decision_service_bp)
except Exception as _e:
    print(f"[WARN] Failed to register education_smart_decision_service_bp: {_e}")
