# Deploy Zelda Remote to your iPhone

This guide documents **everything you do on your Mac and iPhone** to install and run the app. Remote deployment from CI or another machine is not covered; you need **Xcode on the same Mac** you use for development (or a Mac that has your signing certificates).

## What you are deploying

| Piece | Where it runs | Role |
|--------|----------------|------|
| **ZeldaRemote** (your small Xcode app) | iPhone | SwiftUI shell + `ZeldaRemoteRootView` from this repo’s Swift package |
| **`z3cli --bridge`** | Mac | WebSocket → stdio proxy to `z3cli --serve` |
| **LM Studio / MCP** | Mac | Unchanged; phone only speaks JSON-RPC to the bridge |

## Prerequisites

- **Mac:** Xcode **15+** (or current stable), Command Line Tools installed.
- **iPhone:** **iOS 17** or newer (matches `ZeldaRemoteCore` package platforms).
- **Apple ID:** free or paid developer account (free accounts get a **7‑day** signing certificate; reinstall/rebuild before expiry if prompted).
- **Tailscale:** Mac and iPhone logged into the **same tailnet** (recommended).

## Part A — One-time: create the iOS app in Xcode

1. Open **Xcode** → **File → New → Project…** → **iOS** → **App** → Next.
2. **Product Name:** e.g. `ZeldaRemote` (any name).
3. **Team:** your personal team (Apple ID).
4. **Organization Identifier:** e.g. `com.yourhandle` (reverse-DNS you control).
5. **Bundle Identifier** will be `com.yourhandle.ZeldaRemote` — must be **unique** on your account.
6. Interface: **SwiftUI**, Language: **Swift**, Storage: none.
7. **Minimum Deployments:** **iOS 17.0** (or match the package).

### Add this repo’s Swift package

1. **File → Add Package Dependencies…** → **Add Local…**
2. Select the directory: **`…/z3cli/ios/ZeldaRemoteCore`** (folder that contains `Package.swift`).
3. Add **ZeldaRemoteCore** to your **app target** (target → **General** → **Frameworks, Libraries, and Embedded Content** → embed if required; for a dynamic library, “Do Not Embed” is often enough for a local SPM app target—use Xcode’s default if unsure).

### App entry point

Replace your generated `*App.swift` with the template from the repo, or paste:

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

(Identical copy: [`ios/XcodeAppTemplate/ZeldaRemoteApp.swift`](../../ios/XcodeAppTemplate/ZeldaRemoteApp.swift).)

### App icon

This repo includes a ready-made asset catalog with all required sizes:

- Folder: [`ios/ZeldaRemoteAppIcon/Assets.xcassets`](../../ios/ZeldaRemoteAppIcon/Assets.xcassets) (`AppIcon` + `AppIcon-1024.png` master).

In Xcode: drag **`ZeldaRemoteAppIcon/Assets.xcassets`** into your project, then **App target → General → App Icons and Launch Screen → App Icon** → select **`AppIcon`**. Details: [`ios/ZeldaRemoteAppIcon/README.md`](../../ios/ZeldaRemoteAppIcon/README.md).

### App Transport Security (plain `ws://`)

The bridge uses **`ws://`**, not `https`. For development you must relax ATS for that host:

1. Select the **app target** → **Info** tab.
2. Add **App Transport Security Settings** (dictionary).
3. Either:
   - **Recommended:** add **Exception Domains** → a key matching your **Tailscale MagicDNS** hostname (e.g. `my-mac.tail1234.ts.net`) → **Exception Allows Insecure HTTP Loads** = **YES**; **Includes Subdomains** if you use subdomains; **Exception Minimum TLS Version** optional; or  
   - **Quick & personal only:** **Allow Arbitrary Loads** = **YES** (remove before any App Store / shared build).

Raw `100.x.y.z` IP addresses are painful with ATS exception domains; prefer **MagicDNS hostname** in the WebSocket URL when possible.

## Part B — Signing and running on a physical iPhone

1. **Connect** the iPhone with USB **or** pair for **wireless debugging** (Xcode → **Window → Devices and Simulators** → select device → enable **Connect via network** after a successful USB pairing once).
2. Unlock the iPhone; if prompted, **Trust** the computer.
3. In Xcode, open the **scheme** dropdown (toolbar) → select **your iPhone** (not a simulator).
4. Select the **app target** → **Signing & Capabilities**:
   - Enable **Automatically manage signing**.
   - **Team:** your Apple ID team.
5. Press **Run** (▶). First install may fail until the device is trusted:
   - On iPhone: **Settings → General → VPN & Device Management** (or **Device Management**) → tap your developer app → **Trust**.

After a successful run, the app stays on the phone until you delete it. Rebuild/re-run from Xcode to update.

## Part C — Mac: bridge + LM Studio (every hacking session)

From the **z3cli repo root**:

```bash
pip install 'z3cli[bridge]'
```

Set a token and start the bridge (script loads `.bridge.env` if present):

```bash
export Z3CLI_BRIDGE_TOKEN='your-long-secret'
./scripts/run-ios-bridge.sh
```

Details and env file layout: [`bridge.env.example`](./bridge.env.example), [`QUICKSTART-IPHONE.md`](./QUICKSTART-IPHONE.md).

## Part D — On the iPhone: connect once per “cold start”

1. Open the app → **Connect** tab.
2. **WebSocket URL:** `ws://<tailscale-ip-or-magicdns>:8765` (see script output on the Mac).
3. **Bridge token:** same value as `Z3CLI_BRIDGE_TOKEN`.
4. Tap **Connect**. URL and token are **saved** in UserDefaults for the next launch (not Keychain—fine for personal dev).

Use **Chat** to verify streaming; **Host actions** can hit `/sessions`, `/status`, or JSON-RPC `models` / `status`.

## Updating the app after you change `ZeldaRemoteCore`

1. Pull latest `z3cli` on the Mac.
2. In Xcode: **File → Packages → Reset Package Caches** (only if something is stuck), then **Resolve Package Versions** / build again.
3. **Run** on the device to reinstall.

## Optional: TestFlight / App Store

Not set up in this repo. For distribution beyond your own device you would add an app record in App Store Connect, archive, upload, and use TestFlight internal testing—out of scope here.

## Troubleshooting (deploy-specific)

| Issue | What to do |
|-------|------------|
| **Signing failed / no team** | Add Apple ID under Xcode → **Settings → Accounts**; pick Team on target. |
| **Untrusted developer** | iPhone **Settings → General → VPN & Device Management** → Trust. |
| **Could not launch …** | Reboot device; disconnect/reconnect USB; clear **Derived Data** (Xcode Settings → Locations). |
| **Wireless install fails** | Pair with USB once; same Wi‑Fi as Mac; try USB again. |
| **App installs but WebSocket fails** | Tailscale on both sides; bridge running; ATS; token match. |

## Related docs

- [Quickstart (condensed)](./QUICKSTART-IPHONE.md) — same flow, fewer signing details  
- [Bridge protocol](./03-bridge.md)  
- [Validation checklist](./06-validation-gates.md)
