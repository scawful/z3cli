import SwiftUI

/// Top-level SwiftUI shell: Chat, Workflows, Settings. Embed in an iOS `App` target.
public struct ZeldaRemoteRootView: View {
    @StateObject private var store = BackendStore()
    @State private var wsURLString = ""
    @State private var token = ""
    @State private var input = ""
    @State private var selectedTab = 0

    public init() {}

    public var body: some View {
        TabView(selection: $selectedTab) {
            chatTab
                .tabItem { Label("Chat", systemImage: "bubble.left.and.bubble.right") }
                .tag(0)
            workflowsTab
                .tabItem { Label("Zelda", systemImage: "gamecontroller") }
                .tag(1)
            settingsTab
                .tabItem { Label("Connect", systemImage: "link") }
                .tag(2)
        }
        .sheet(isPresented: Binding(
            get: { store.pendingPermission != nil },
            set: { presented in
                if !presented, store.pendingPermission != nil {
                    Task { try? await store.denyTool() }
                }
            }
        )) {
            if let perm = store.pendingPermission {
                permissionSheet(perm)
            }
        }
        .onAppear {
            if wsURLString.isEmpty {
                wsURLString = BridgeConnectionDefaults.loadURL()
            }
            if token.isEmpty {
                token = BridgeConnectionDefaults.loadToken()
            }
        }
    }

    private var chatTab: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 8) {
                            ForEach(store.messages) { msg in
                                messageRow(msg)
                            }
                            if !store.streamingContent.isEmpty || !store.streamingThinking.isEmpty {
                                streamingBlock
                            }
                        }
                        .padding()
                    }
                    .onChange(of: store.messages.count) { _, _ in
                        if let id = store.messages.last?.id {
                            withAnimation { proxy.scrollTo(id, anchor: .bottom) }
                        }
                    }
                }
                Divider()
                HStack {
                    TextField("Message", text: $input, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .lineLimit(1 ... 4)
                    Button("Send") {
                        Task { await sendChat() }
                    }
                    .disabled(input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.isStreaming)
                }
                .padding()
            }
            .navigationTitle("Zelda Remote")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    if store.isStreaming {
                        Button("Stop") {
                            Task { try? await store.cancelStream() }
                        }
                    }
                }
            }
        }
    }

    private var workflowsTab: some View {
        NavigationStack {
            List(ZeldaWorkflows.presets) { preset in
                Button(preset.title) {
                    input = preset.prompt
                    selectedTab = 0
                }
            }
            .navigationTitle("Workflows")
        }
    }

    private var settingsTab: some View {
        NavigationStack {
            Form {
                Section("Tailscale / bridge") {
                    TextField("WebSocket URL", text: $wsURLString)
                        .textContentType(.URL)
                        #if os(iOS)
                            .keyboardType(.URL)
                            .textInputAutocapitalization(.never)
                        #endif
                    SecureField("Bridge token", text: $token)
                    Button("Connect") { connectFromForm() }
                    Button("Disconnect", role: .destructive) {
                        store.disconnect()
                    }
                }
                if let cfg = store.config {
                    Section("Host") {
                        LabeledContent("Workspace", value: cfg.workspace)
                        LabeledContent("Model", value: cfg.activeModel)
                        LabeledContent("Session", value: cfg.sessionPath)
                    }
                }
                Section("Host actions") {
                    ForEach(Array(ZeldaWorkflows.slashHints.enumerated()), id: \.offset) { _, row in
                        Button(row.label) {
                            Task {
                                do {
                                    let result = try await store.sendCommand(cmd: row.cmd, args: row.args)
                                    store.addSystemMessage(String(describing: result))
                                } catch {
                                    store.addSystemMessage("Error: \(error.localizedDescription)")
                                }
                            }
                        }
                    }
                    Button("Models (JSON-RPC)") {
                        Task {
                            do {
                                let result = try await store.fetchModelsList()
                                store.addSystemMessage(String(describing: result))
                            } catch {
                                store.addSystemMessage("Error: \(error.localizedDescription)")
                            }
                        }
                    }
                    Button("Status (JSON-RPC)") {
                        Task {
                            do {
                                let result = try await store.fetchStatusRPC()
                                store.addSystemMessage(String(describing: result))
                            } catch {
                                store.addSystemMessage("Error: \(error.localizedDescription)")
                            }
                        }
                    }
                }
            }
            .navigationTitle("Settings")
        }
    }

    private func messageRow(_ msg: ZRMessage) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(msg.role.uppercased())
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(msg.content)
                .font(.body)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(8)
        .background(Color.secondary.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .id(msg.id)
    }

    private var streamingBlock: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !store.streamingThinking.isEmpty {
                Text(store.streamingThinking)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if !store.streamingContent.isEmpty {
                Text(store.streamingContent)
                    .font(.body)
            }
            if let name = store.activeToolName {
                let elapsed = store.activeToolStartedAt.map { Int(Date().timeIntervalSince($0)) } ?? 0
                Text("Tool: \(name) (\(elapsed)s)")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(8)
        .background(Color.accentColor.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    @ViewBuilder
    private func permissionSheet(_ perm: ZRPendingPermission) -> some View {
        NavigationStack {
            Form {
                Section("Tool") {
                    Text(perm.server.isEmpty ? perm.name : "\(perm.server): \(perm.name)")
                    Text(perm.arguments)
                        .font(.caption)
                        .textSelection(.enabled)
                }
                Section {
                    Button("Allow once") {
                        Task { try? await store.approveTool() }
                    }
                    Button("Allow session") {
                        Task { try? await store.approveToolForSession() }
                    }
                    Button("Deny once", role: .destructive) {
                        Task { try? await store.denyTool() }
                    }
                    Button("Deny session", role: .destructive) {
                        Task { try? await store.denyToolForSession() }
                    }
                }
            }
            .navigationTitle("Permission")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") {
                        Task { try? await store.denyTool() }
                    }
                }
            }
        }
    }

    private func connectFromForm() {
        let trimmed = wsURLString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), !token.isEmpty else { return }
        BridgeConnectionDefaults.save(url: trimmed, token: token)
        store.connect(url: url, bearerToken: token)
    }

    private func sendChat() async {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        input = ""
        do {
            try await store.sendMessage(text)
        } catch {
            store.addSystemMessage("Error: \(error.localizedDescription)")
        }
    }
}
