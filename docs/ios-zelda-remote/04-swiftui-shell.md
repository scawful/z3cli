# SwiftUI shell (native)

The reusable iOS/macOS Swift module lives under [`ios/ZeldaRemoteCore`](../../ios/ZeldaRemoteCore) (Swift Package Manager).

## Contents

| Area | Source | Role |
|------|--------|------|
| NDJSON classification | `Sources/ZeldaRemoteCore/ParsedRPC.swift` | Same line grammar as stdio |
| App models | `Sources/ZeldaRemoteCore/AppModels.swift` | `ZRAppConfig`, `ZRMessage`, … from snake_case JSON |
| Transport | `Sources/ZeldaRemoteCore/BackendClient.swift` | `URLSessionWebSocketTask` + request/notify |
| State | `Sources/ZeldaRemoteCore/BackendStore.swift` | Ports `useBackend` transitions |
| UI | `Sources/ZeldaRemoteCore/Views/ZeldaRemoteRootView.swift` | `TabView`: Chat / Workflows / Connect |
| Presets | `Sources/ZeldaRemoteCore/ZeldaWorkflows.swift` | Zelda-oriented quick prompts |

## Embedding in an iOS App target

1. In Xcode: **File → Add Package Dependencies…** → add the local folder `ios/ZeldaRemoteCore`.
2. Link **ZeldaRemoteCore** to your app target.
3. In `@main` `App` `body`:

```swift
import SwiftUI
import ZeldaRemoteCore

@main
struct ZeldaRemoteApp: App {
    var body: some Scene {
        WindowGroup {
            ZeldaRemoteRootView()
        }
    }
}
```

4. **Info.plist**: if you use cleartext `ws://` to a MagicDNS hostname, you may need an **App Transport Security** exception for that host; prefer **wss://** behind a TLS-terminating proxy when not on pure Tailscale paths.

## Navigation model

- **Chat** — message list, streaming deltas, Stop, permission sheet (mirrors Ink `PermissionDialog` behavior: dismiss / swipe → `deny-once`).
- **Zelda** — inserts preset prompts into chat.
- **Connect** — WebSocket URL + token, Connect/Disconnect, host actions (`/sessions`, `/status`, JSON-RPC `models`).

## Mobile-specific states (MVP coverage)

| State | Behavior |
|-------|----------|
| Offline / bad URL | `BackendClient` receive loop ends; surface `error` / reconnect from Settings |
| Tool permission | Sheet + `tool/decision` commands |
| Stop streaming | `cancel` notification + local `cancelledStreaming` flag (same idea as Ink) |

## Dynamic Type & accessibility

Follow standard SwiftUI patterns: prefer `LabeledContent`, system fonts, and audit VoiceOver labels on the chat list and permission sheet before shipping.
