// MARK: - 小龙 iOS · 主入口 (Chat / Settings 双 Tab)

import SwiftUI

@main
struct XiaolongIOSApp: App {
    @State private var session = SessionStore()

    var body: some Scene {
        WindowGroup {
            Group {
                if session.loggedIn {
                    TabView {
                        ChatScreen().tabItem { Label("聊天", systemImage: "bubble.left.and.bubble.right") }
                        SettingsScreen().tabItem { Label("设置", systemImage: "gearshape") }
                    }
                } else {
                    LoginScreen()
                }
            }
            .environment(session)
            .tint(session.accent)
        }
    }
}

// MARK: 会话状态 (登录态 / 主题色)
@Observable
final class SessionStore {
    var loggedIn: Bool = APIClient.shared.isLoggedIn
    var username: String = APIClient.shared.savedUser?.username ?? ""
    var themeName: String = ""

    /// 主题色: 服务端主题名 → SwiftUI Color (粉色/深色/海洋/绿/米黄)
    var accent: Color {
        switch themeName.lowercased() {
        case let n where n.contains("粉") || n.contains("pink"):  return Color(red: 0.95, green: 0.45, blue: 0.62)
        case let n where n.contains("海") || n.contains("ocean"): return .blue
        case let n where n.contains("绿") || n.contains("green"): return .green
        case let n where n.contains("深") || n.contains("dark"):  return .indigo
        default: return .orange                                   // 小龙默认琥珀
        }
    }

    func refreshTheme() {
        Task {
            if let t = await APIClient.shared.myTheme() {
                await MainActor.run { self.themeName = t }
            }
        }
    }

    func applyAuth(token: String, user: XLUser) {
        APIClient.shared.token = token
        UserDefaults.standard.set(user.username, forKey: "xl_username")
        if let d = try? JSONEncoder().encode(user) {
            UserDefaults.standard.set(d, forKey: "xl_user")
        }
        username = user.username
        loggedIn = true
        refreshTheme()
    }

    func logout() {
        APIClient.shared.token = nil
        loggedIn = false
        themeName = ""
    }
}
