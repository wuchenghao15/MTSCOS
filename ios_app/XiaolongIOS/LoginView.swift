// MARK: - 小龙 iOS · 登录 / 注册

import SwiftUI

struct LoginScreen: View {
    @Environment(SessionStore.self) private var session
    @State private var mode: Mode = .login
    @State private var username = ""
    @State private var password = ""
    @State private var busy = false
    @State private var err = ""

    enum Mode { case login, register }

    var body: some View {
        VStack(spacing: 22) {
            Spacer()
            Image(systemName: "dragon")
                .font(.system(size: 64)).foregroundStyle(.orange)
            Text("小龙").font(.largeTitle.bold())
            Text("MTSCOS 移动聊天引擎").font(.caption).foregroundStyle(.secondary)

            Picker("", selection: $mode) {
                Text("登录").tag(Mode.login)
                Text("注册").tag(Mode.register)
            }.pickerStyle(.segmented).padding(.horizontal, 30)

            VStack(spacing: 12) {
                TextField("用户名 (3-32位)", text: $username)
                    .textFieldStyle(.roundedBorder).autocorrectionDisabled().textInputAutocapitalization(.never)
                SecureField("密码 (至少8位)", text: $password)
                    .textFieldStyle(.roundedBorder)
            }.padding(.horizontal, 30)

            if !err.isEmpty {
                Text(err).font(.footnote).foregroundStyle(.red).padding(.horizontal)
            }

            Button {
                submit()
            } label: {
                if busy { ProgressView().frame(maxWidth: .infinity) }
                else { Text(mode == .login ? "登录" : "注册").bold().frame(maxWidth: .infinity) }
            }
            .buttonStyle(.borderedProminent).controlSize(.large)
            .padding(.horizontal, 30)
            .disabled(busy || username.count < 3 || password.count < 8)

            Spacer()
            Text(APIClient.shared.baseURL)
                .font(.caption2).foregroundStyle(.tertiary)
        }
    }

    private func submit() {
        busy = true; err = ""
        Task {
            do {
                let r = mode == .login
                    ? try await APIClient.shared.login(username, password)
                    : try await APIClient.shared.register(username, password)
                await MainActor.run {
                    busy = false
                    if r.success, let tok = r.token, let u = r.user {
                        session.applyAuth(token: tok, user: u)
                    } else {
                        err = r.message ?? r.error ?? "失败"
                    }
                }
            } catch {
                await MainActor.run { busy = false; err = error.localizedDescription }
            }
        }
    }
}
