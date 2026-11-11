// MARK: - 小龙 iOS · 网络层 (X-XL-Token 认证 + SSE 流式)

import Foundation

struct XLUser: Codable {
    let user_id: String
    let username: String
    let role: String?
}

struct AuthResponse: Codable {
    let success: Bool
    let token: String?
    let user: XLUser?
    let message: String?
    let error: String?
}

struct ToolCallEvent: Identifiable {
    let id = UUID()
    let tool: String
    let ok: Bool?
    let summary: String
}

struct SSEEvent {
    var type: String = ""
    var delta: String = ""
    var tool: String = ""
    var ok: Bool?
    var summary: String = ""
    var answer: String = ""
    var sessionID: String = ""
    var messageID: Int?
    var error: String = ""
}

enum APIError: LocalizedError {
    case badURL, http(Int), decode(String), empty
    var errorDescription: String? {
        switch self {
        case .badURL: return "服务器地址无效"
        case .http(let c): return "HTTP \(c)"
        case .decode(let m): return "响应解析失败: \(m)"
        case .empty: return "空响应"
        }
    }
}

final class APIClient: @unchecked Sendable {
    static let shared = APIClient()
    private let session: URLSession

    init() {
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 600      // 工具循环可能较长
        cfg.timeoutIntervalForResource = 900
        session = URLSession(configuration: cfg)
    }

    var baseURL: String {
        get { UserDefaults.standard.string(forKey: "xl_server") ?? "http://100.121.98.15:5001" }
        set { UserDefaults.standard.set(newValue.trimmingCharacters(in: CharacterSet(charactersIn: "/")), forKey: "xl_server") }
    }
    var token: String? {
        get { UserDefaults.standard.string(forKey: "xl_token") }
        set { UserDefaults.standard.set(newValue, forKey: "xl_token") }
    }
    var savedUser: XLUser? {
        guard let d = UserDefaults.standard.data(forKey: "xl_user") else { return nil }
        return try? JSONDecoder().decode(XLUser.self, from: d)
    }
    var isLoggedIn: Bool { token != nil && savedUser != nil }

    private func request(_ path: String, method: String = "POST", body: [String: Any]? = nil) throws -> URLRequest {
        guard let url = URL(string: baseURL + path) else { throw APIError.badURL }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token { req.setValue(token, forHTTPHeaderField: "X-XL-Token") }
        if let body { req.httpBody = try JSONSerialization.data(withJSONObject: body) }
        return req
    }

    private var deviceID: String {
        UIDevice.current.identifierForVendor?.uuidString ?? "ios-\(Int.random(in: 1000...9999))"
    }

    // MARK: 登录 / 注册
    func login(_ username: String, _ password: String) async throws -> AuthResponse {
        let req = try request("/api/xiaolong/token", body: ["username": username, "password": password, "device_id": deviceID])
        return try await execute(req)
    }

    func register(_ username: String, _ password: String) async throws -> AuthResponse {
        let req = try request("/api/xiaolong/register", body: ["username": username, "password": password, "device_id": deviceID])
        return try await execute(req)
    }

    private func execute(_ req: URLRequest) async throws -> AuthResponse {
        let (data, resp) = try await session.data(for: req)
        guard let http = resp as? HTTPURLResponse else { throw APIError.empty }
        guard (200..<300).contains(http.statusCode) else {
            if let ar = try? JSONDecoder().decode(AuthResponse.self, from: data) { return ar }
            throw APIError.http(http.statusCode)
        }
        do { return try JSONDecoder().decode(AuthResponse.self, from: data) }
        catch { throw APIError.decode(error.localizedDescription) }
    }

    // MARK: SSE 流式聊天 — 逐事件回调
    func chatStream(message: String, sessionID: String, model: String,
                    onEvent: @escaping @Sendable (SSEEvent) -> Void) async throws {
        var req = try request("/api/xiaolong/chat/stream",
                              body: ["message": message, "session_id": sessionID, "model": model])
        req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        let (bytes, resp) = try await session.bytes(for: req)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
            throw APIError.http((resp as? HTTPURLResponse)?.statusCode ?? -1)
        }
        var buf = ""
        for try await line in bytes.lines {
            guard line.hasPrefix("data: ") else { continue }
            buf = String(line.dropFirst(6))
            guard let d = buf.data(using: .utf8),
                  let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { continue }
            var ev = SSEEvent()
            ev.type = obj["type"] as? String ?? ""
            switch ev.type {
            case "delta":      ev.delta = obj["text"] as? String ?? ""
            case "tool_start": ev.tool = obj["tool"] as? String ?? ""
            case "tool_done":
                ev.tool = obj["tool"] as? String ?? ""
                ev.ok = obj["ok"] as? Bool
                ev.summary = obj["summary"] as? String ?? ""
            case "done":
                ev.answer = obj["answer"] as? String ?? ""
                ev.sessionID = obj["session_id"] as? String ?? ""
                ev.messageID = obj["message_id"] as? Int
            case "error":      ev.error = obj["error"] as? String ?? "unknown"
            default: break
            }
            onEvent(ev)
        }
    }

    // MARK: 反馈 / 主题
    func feedback(messageID: Int, up: Bool) async throws -> Bool {
        let req = try request("/api/chat-feedback",
                              body: ["message_id": messageID, "feedback": up ? "up" : "down"])
        let (data, _) = try await session.data(for: req)
        return (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["success"] as? Bool ?? false
    }

    struct ThemeResponse: Codable {
        let success: Bool
        let theme: String?
        let message: String?
    }
    func myTheme() async -> String? {
        guard let req = try? request("/api/user-theme", method: "GET") else { return nil }
        guard let (data, _) = try? await session.data(for: req),
              let tr = try? JSONDecoder().decode(ThemeResponse.self, from: data) else { return nil }
        return tr.theme
    }
}

import UIKit
