# iOS Zelda Remote (native + protocol reuse)

Design and implementation artifacts for a **SwiftUI** client that speaks the same JSON-RPC line protocol as the Ink frontend, plus a **WebSocket bridge** for Tailscale (or LAN) access to a host running `z3cli --serve` and LM Studio.

## Doc index

**→ [Deploy to your iPhone (full guide)](./DEPLOY-TO-IPHONE.md)** — Xcode signing, device install, bridge, connect  

**→ [Quickstart (condensed)](./QUICKSTART-IPHONE.md)**

1. [Reuse inventory](./01-reuse-inventory.md)
2. [Protocol → Swift mapping](./02-protocol-swift-mapping.md)
3. [WebSocket bridge](./03-bridge.md)
4. [SwiftUI shell](./04-swiftui-shell.md)
5. [Zelda workflows](./05-zelda-workflows.md)
6. [Validation gates](./06-validation-gates.md)

## Code

- Swift package: [`../../ios/ZeldaRemoteCore`](../../ios/ZeldaRemoteCore)
- App icon asset catalog: [`../../ios/ZeldaRemoteAppIcon`](../../ios/ZeldaRemoteAppIcon)
- Bridge: [`../../z3cli/app/ws_bridge.py`](../../z3cli/app/ws_bridge.py)
