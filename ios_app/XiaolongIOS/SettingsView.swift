// MARK: - 小龙 iOS · 设置 (服务器 / 模型 / 主题 / 登出)

import SwiftUI

struct SettingsScreen: View {
    @Environment(SessionStore.self) private var session
    @State private var server = APIClient.shared.baseURL
    @State private var model = UserDefaults.standard.string(forKey: "xl_model") ?? "qwen2.5:7b"
    @State private var ping = ""
    @State private var testing = false

    let models = ["qwen2.5:7b", "qwen2.5:3b", "qwen2.5:14b-q5_K_M", "qwen2.5-coder:14b", "qwen2.5-coder:7b"]

    var body: some View {
        NavigationStack {
            Form {
                Section("当前用户") {
                    LabeledContent("用户名", value: session.username)
                    if !session.themeName.isEmpty {
                        LabeledContent("我的主题", value: session.themeName)
                    }
                }
                Section("服务器 (Tailscale / 局域网)") {
                    TextField("http://100.121.98.15:5001", text: $server)
                        .keyboardType(.URL).autocorrectionDisabled().textInputAutocapitalization(.never)
                    Button {
                        testing = true; ping = ""
                        Task {
                            APIClient.shared.baseURL = server
                            guard let url = URL(string: server + "/api/xiaolong/health") else {
                                await MainActor.run { testing = false; ping = "地址无效" }; return
                            }
                            do {
                                let (_, resp) = try await URLSession.shared.data(from: url)
                                let code = (resp as? HTTPURLResponse)?.statusCode ?? -1
                                await MainActor.run {
                                    testing = false
                                    ping = code == 200 ? "服务器在线" : "HTTP \(code)"
                                }
                            } catch {
                                await MainActor.run { testing = false; ping = error.localizedDescription }
                            }
                        }
                    } label: {
                        if testing { ProgressView(); } else { Text("测试连接") }
                    }
                    if !ping.isEmpty { Text(ping).font(.footnote) }
                }
                Section("模型") {
                    Picker("默认模型", selection: $model) {
                        ForEach(models, id: \.self) { Text($0).tag($0) }
                    }
                    .onChange(of: model) { _, nv in
                        UserDefaults.standard.set(nv, forKey: "xl_model")
                    }
                }
                Section("关于") {
                    LabeledContent("版本", value: "1.0 (原生 SwiftUI)")
                    LabeledContent("流式", value: "SSE 实时 + 工具事件")
                    LabeledContent("反馈", value: "👍👎 → 质量工单入厅")
                }
                Section {
                    Button("退出登录", role: .destructive) { session.logout() }
                }
            }
            .navigationTitle("设置")
        }
    }
}
