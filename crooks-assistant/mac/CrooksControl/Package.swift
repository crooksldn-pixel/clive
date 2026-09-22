// swift-tools-version:5.9
//
// CROOKS Control — the Mac's control centre for CROOKS OS.
//
// This package is two things, and the split is the whole point of it.
//
//   CrooksControlCore   Foundation only. EVERY decision the app makes lives here: what each
//                       document from `crooks-control` means, whether CROOKS OS is actually
//                       up (as opposed to merely having been asked to start), whether an
//                       update really worked, whether the CROOKS Pad is connected or the
//                       route to it merely exists, and which plain sentence the owner is
//                       shown when something fails. It builds, and its tests run, on any
//                       machine with a Swift toolchain.
//
//   CrooksControl       The SwiftUI/AppKit app that DRAWS the core. It holds no decision of
//                       its own: it reads one `Dashboard` value and lays it out. It can only
//                       be built on a Mac.
//
// The app target is declared only when this manifest is compiled on macOS. That is not a
// nicety. SwiftUI and AppKit do not exist off Apple's platforms, so a package that always
// declared the app target could not be built or tested anywhere else — and the core's tests,
// which are the ones that actually protect the product, would be unrunnable on the machine
// most likely to be asked to run them. SwiftPM compiles this manifest on the machine doing
// the building, so `#if os(macOS)` here means exactly "this machine can build a Mac app".
//
// On a Mac:      swift build          (core + app)   then  ./build.sh --install
// Anywhere else: swift build          (core alone)
//                swift test           (every core test; nothing is skipped or faked)

import PackageDescription

var products: [Product] = [
    .library(name: "CrooksControlCore", targets: ["CrooksControlCore"]),
]

var targets: [Target] = [
    .target(name: "CrooksControlCore", path: "Sources/CrooksControlCore"),
    .testTarget(
        name: "CrooksControlCoreTests",
        dependencies: ["CrooksControlCore"],
        path: "Tests/CrooksControlCoreTests"
    ),
]

#if os(macOS)
products.append(.executable(name: "CrooksControl", targets: ["CrooksControl"]))
targets.append(
    .executableTarget(
        name: "CrooksControl",
        dependencies: ["CrooksControlCore"],
        path: "Sources/CrooksControl"
    )
)
#endif

let package = Package(
    name: "CrooksControl",
    platforms: [.macOS(.v13)],
    products: products,
    targets: targets
)
