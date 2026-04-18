# Quickstart: try on your iPhone

Shortest path: **Tailscale** on Mac + iPhone (same tailnet), **WebSocket bridge** on the Mac, **small Xcode app** that depends on `ZeldaRemoteCore`.

**For Xcode signing, Trust Developer, wireless debugging, and ATS details, use the full doc:** [Deploy to your iPhone](./DEPLOY-TO-IPHONE.md).

## 1) Mac: Tailscale IP

On the Mac that runs LM Studio + z3cli:

```bash
tailscale ip -4
```

Note the `100.x.y.z` address (or use your [MagicDNS](https://tailscale.com/kb/1081/magicdns/) name like `your-mac.tailxxxx.ts.net` if you prefer a hostname).

## 2) Mac: install bridge extra + token

From the **z3cli repo root**:

```bash
pip install 'z3cli[bridge]'
export Z3CLI_BRIDGE_TOKEN='pick-a-long-random-secret'
```

Optional: copy the example env file and edit:

```bash
cp docs/ios-zelda-remote/bridge.env.example .bridge.env
# edit .bridge.env — never commit real secrets
```

## 3) Mac: start the bridge

Easiest:

```bash
./scripts/run-ios-bridge.sh
```

Or manually:

```bash
python -m z3cli --bridge --bridge-host 0.0.0.0 --bridge-port 8765 --bridge-token "$Z3CLI_BRIDGE_TOKEN" -- --workspace "$HOME/src/hobby/oracle-of-secrets"
```

Adjust `--workspace`, `--rom`, etc. after `--` the same way you would for `z3cli --serve`.

Leave this terminal open while testing.

## 4) iPhone: Xcode app (one-time)

1. Open **Xcode** → **File → New → Project** → **App**.
2. Product name: e.g. `ZeldaRemote`, Interface **SwiftUI**, minimum **iOS 17**.
3. **File → Add Package Dependencies…** → **Add Local…** → select the folder  
   `z3cli/ios/ZeldaRemoteCore` (the one that contains `Package.swift`).
4. Add **ZeldaRemoteCore** to the app target (General → Frameworks).
5. Replace the generated `*App.swift` body with:

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

6. **App Transport Security** (needed for plain `ws://` during dev):  
   In the app target → **Info** → add row **App Transport Security Settings** → **Exception Domains** → add a domain entry:
   - If you connect with **`ws://something.tailxxxx.ts.net`** use that hostname as the domain key and set **Exception Allows Insecure HTTP Loads** = YES.  
   - If you only have a **raw `100.x` IP**, ATS domain exceptions are awkward; for a **personal device** you may temporarily set **Allow Arbitrary Loads** = YES under **App Transport Security Settings** while testing, then remove it.

7. **App icon:** drag [`ios/ZeldaRemoteAppIcon/Assets.xcassets`](../../ios/ZeldaRemoteAppIcon/Assets.xcassets) into the project; set **App Icon** to `AppIcon` (see [`ios/ZeldaRemoteAppIcon/README.md`](../../ios/ZeldaRemoteAppIcon/README.md)).

8. Build & run on a **physical iPhone** (same Tailscale account as the Mac).

## 6) iPhone: connect in the app

1. Open the **Connect** tab.
2. **WebSocket URL:** `ws://100.x.y.z:8765` (or `ws://your-mac.tailxxxx.ts.net:8765`).
3. **Bridge token:** same string as `Z3CLI_BRIDGE_TOKEN` on the Mac.
4. Tap **Connect** — URL and token are **saved** for next launch.

Go to **Chat** and send a message; you should see streaming and token counts after `ready`.

## Troubleshooting

| Symptom | Fix |
|--------|-----|
| Can’t connect / hangs | Confirm Mac bridge is running; iPhone on Tailscale; URL uses `ws://` and correct port; firewall allows inbound on `8765` (often OK on tailnet). |
| ATS / “secure connection” errors | Add ATS exception (step 6) or use TLS termination + `wss://` later. |
| `unauthorized` / disconnect | Token mismatch: same exact `Z3CLI_BRIDGE_TOKEN` on Mac and in the app. |
| No models / LM errors | LM Studio must be up on the **Mac**; z3cli flags after `--` must point at your ROM/workspace. |

## Files in this repo

| Item | Purpose |
|------|---------|
| [`scripts/run-ios-bridge.sh`](../../scripts/run-ios-bridge.sh) | Prints tailnet URL hint and runs `--bridge` |
| [`docs/ios-zelda-remote/bridge.env.example`](./bridge.env.example) | Copy to repo-root `.bridge.env` (gitignored pattern — add to your global gitignore if needed) |
| [`ios/ZeldaRemoteCore`](../../ios/ZeldaRemoteCore) | Swift package + `ZeldaRemoteRootView` |
| [`ios/ZeldaRemoteAppIcon`](../../ios/ZeldaRemoteAppIcon) | `AppIcon` asset catalog (iPhone / iPad / 1024) |
