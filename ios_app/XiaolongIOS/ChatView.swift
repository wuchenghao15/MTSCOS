// MARK: - 小龙 iOS · 聊天主界面 (SSE 流式 + 工具事件 + 反馈)

import SwiftUI

struct ChatMessage: Identifiable {
    let id = UUID()
    var role: String          // user / assistant
    var text: String
    var tools: [ToolCallEvent] = []
    var messageID: Int?       // 服务端 id, 用于反馈
    var streaming = false
}

@Observable
final class ChatVM {
    var messages: [ChatMessage] = []
    var input = ""
    var busy = false
    var sessionID = "ios_\(Int(Date().timeIntervalSince1970))"
    var model = UserDefaults.standard.string(forKey: "xl_model") ?? "qwen2.5:7b"
    var lastError = ""

    func send() {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !busy else { return }
        input = ""; busy = true; lastError = ""
        messages.append(ChatMessage(role: "user", text: text))
        var reply = ChatMessage(role: "assistant", text: "", streaming: true)
        messages.append(reply)
        var replyIdx = messages.count - 1

        Task {
            do {
                try await APIClient.shared.chatStream(message: text, sessionID: sessionID, model: model) { [weak self] ev in
                    Task { @MainActor in
                        guard let self else { return }
                        // 找到当前流式中的 assistant 消息
                        replyIdx = self.messages.lastIndex(where: { $0.streaming }) ?? replyIdx
                        switch ev.type {
                        case "delta":
                            if replyIdx < self.messages.count {
                                self.messages[replyIdx].text += ev.delta
                            }
                        case "tool_start":
                            if replyIdx < self.messages.count {
                                self.messages[replyIdx].text = ""      // 临时 delta 清空
                                self.messages[replyIdx].tools.append(
                                    ToolCallEvent(tool: ev.tool, ok: nil, summary: "执行中…"))
                            }
                        case "tool_done":
                            if replyIdx < self.messages.count, let i = self.messages[replyIdx].tools.lastIndex(where: { $0.tool == ev.tool }) {
                                self.messages[replyIdx].tools[i] =
                                    ToolCallEvent(tool: ev.tool, ok: ev.ok, summary: ev.summary)
                            }
                        case "done":
                            if replyIdx < self.messages.count {
                                self.messages[replyIdx].text = ev.answer
                                self.messages[replyIdx].messageID = ev.messageID
                                self.messages[replyIdx].streaming = false
                            }
                            self.busy = false
                        case "error":
                            self.lastError = ev.error
                            self.busy = false
                            if replyIdx < self.messages.count {
                                self.messages[replyIdx].text = "⚠️ " + ev.error
                                self.messages[replyIdx].streaming = false
                            }
                        default: break
                        }
                    }
                }
            } catch {
                await MainActor.run {
                    lastError = error.localizedDescription
                    busy = false
                    if replyIdx < messages.count {
                        messages[replyIdx].text = "⚠️ \(error.localizedDescription)"
                        messages[replyIdx].streaming = false
                    }
                }
            }
        }
    }

    func feedback(_ msg: ChatMessage, up: Bool) {
        guard let mid = msg.messageID else { return }
        Task { _ = try? await APIClient.shared.feedback(messageID: mid, up: up) }
    }
}

struct ChatScreen: View {
    @Environment(SessionStore.self) private var session
    @State private var vm = ChatVM()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            ForEach(vm.messages) { m in
                                Bubble(msg: m) { up in vm.feedback(m, up: up) }
                                    .id(m.id)
                            }
                        }.padding(12)
                    }
                    .onChange(of: vm.messages.count) { _, _ in
                        if let last = vm.messages.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } }
                    }
                    .onChange(of: vm.messages.last?.text) { _, _ in
                        if let last = vm.messages.last, last.streaming {
                            proxy.scrollTo(last.id, anchor: .bottom)
                        }
                    }
                }
                if !vm.lastError.isEmpty {
                    Text(vm.lastError).font(.caption2).foregroundStyle(.red).padding(.horizontal)
                }
                HStack(spacing: 8) {
                    TextField("问小龙…", text: $vm.input, axis: .vertical)
                        .textFieldStyle(.roundedBorder).lineLimit(1...4)
                        .onSubmit { vm.send() }
                    Button {
                        vm.send()
                    } label: {
                        Image(systemName: "arrow.up.circle.fill").font(.title2)
                    }
                    .disabled(vm.busy || vm.input.trimmingCharacters(in: .whitespaces).isEmpty)
                }.padding(10)
            }
            .navigationTitle("小龙")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(leading) {
                    Text(session.username).font(.caption).foregroundStyle(.secondary)
                }
                ToolbarItem(trailing) {
                    if vm.busy { ProgressView() }
                }
            }
        }
    }
}

// MARK: 气泡
struct Bubble: View {
    let msg: ChatMessage
    let onFeedback: (Bool) -> Void
    @State private var fed: String?

    var body: some View {
        HStack {
            if msg.role == "user" { Spacer(minLength: 50) }
            VStack(alignment: .leading, spacing: 6) {
                ForEach(msg.tools) { t in
                    HStack(spacing: 4) {
                        Image(systemName: t.ok == nil ? "gear" : (t.ok! ? "checkmark.circle.fill" : "xmark.circle.fill"))
                            .foregroundStyle(t.ok == nil ? .gray : (t.ok! ? .green : .red))
                            .font(.caption)
                        Text(t.tool).font(.caption.bold())
                        Text(t.summary).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                    }
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .background(.quaternary, in: Capsule())
                }
                if !msg.text.isEmpty {
                    Text(msg.text)
                        .textSelection(.enabled)
                }
                if msg.streaming {
                    ProgressView().scaleEffect(0.7)
                }
                if msg.role == "assistant", !msg.streaming, msg.messageID != nil {
                    HStack(spacing: 10) {
                        if fed == nil {
                            Button { fed = "up"; onFeedback(true) } label: { Image(systemName: "hand.thumbsup").font(.caption) }
                            Button { fed = "down"; onFeedback(false) } label: { Image(systemName: "hand.thumbsdown").font(.caption) }
                        } else {
                            Text(fed == "up" ? "👍 已反馈" : "👎 已反馈·质量工单已入厅").font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                    .buttonStyle(.borderless)
                }
            }
            .padding(12)
            .background(msg.role == "user" ? Color.accentColor.opacity(0.18) : Color(.secondarySystemBackground),
                        in: RoundedRectangle(cornerRadius: 16))
            if msg.role != "user" { Spacer(minLength: 50) }
        }
    }
}
