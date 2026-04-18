// Copy into a new Xcode iOS App target (iOS 17+), after adding the local
// Swift package dependency on ../ZeldaRemoteCore (Package.swift).

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
