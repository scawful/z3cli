# iOS / Swift client (`ZeldaRemoteCore`)

**Deploy to your iPhone:** **[`docs/ios-zelda-remote/DEPLOY-TO-IPHONE.md`](../docs/ios-zelda-remote/DEPLOY-TO-IPHONE.md)** (signing, device install, bridge, connect).  
Condensed flow: **[`QUICKSTART-IPHONE.md`](../docs/ios-zelda-remote/QUICKSTART-IPHONE.md)**.

On the Mac, from the **z3cli repo root**:

```bash
chmod +x scripts/run-ios-bridge.sh   # once
export Z3CLI_BRIDGE_TOKEN='your-secret'
./scripts/run-ios-bridge.sh
```

The app’s **Connect** tab saves WebSocket URL + token in `UserDefaults` for the next launch.

---

Swift package path: **`ZeldaRemoteCore/`** (open `Package.swift` in Xcode or add as a local package dependency).

```bash
cd ZeldaRemoteCore
swift build
swift test
```

Minimal `@main` for a new Xcode app: copy [`XcodeAppTemplate/ZeldaRemoteApp.swift`](XcodeAppTemplate/ZeldaRemoteApp.swift).

**App icon:** drag [`ZeldaRemoteAppIcon/Assets.xcassets`](ZeldaRemoteAppIcon/Assets.xcassets) into your Xcode project and set **App Icon** to `AppIcon` — see [`ZeldaRemoteAppIcon/README.md`](ZeldaRemoteAppIcon/README.md).

See [`../docs/ios-zelda-remote/README.md`](../docs/ios-zelda-remote/README.md) for architecture, bridge setup, and validation.
