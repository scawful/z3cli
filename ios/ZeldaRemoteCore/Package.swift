// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ZeldaRemoteCore",
    platforms: [
        .iOS(.v17),
        .macOS(.v14),
    ],
    products: [
        .library(name: "ZeldaRemoteCore", targets: ["ZeldaRemoteCore"]),
    ],
    targets: [
        .target(
            name: "ZeldaRemoteCore",
            path: "Sources/ZeldaRemoteCore"
        ),
        .testTarget(
            name: "ZeldaRemoteCoreTests",
            dependencies: ["ZeldaRemoteCore"],
            path: "Tests/ZeldaRemoteCoreTests"
        ),
    ]
)
