[Flask Blueprint — 按功能分包]
32 个 API Blueprint 文件，统一注册后新增 405 路由：
- api/ : 业务 API（ai_*/education/k12/listening/rule/security/arduino/vikey ...）
- ai/ : AI Agent 类（120+ 个智能体实现）
- services/ : 服务层（auth_service / vikey_auth / hook_service / user_container）
- middlewares/ : Flask 中间件
