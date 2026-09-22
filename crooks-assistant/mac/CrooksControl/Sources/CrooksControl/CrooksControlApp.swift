import AppKit
import SwiftUI
import CrooksControlCore

// The app. A window that IS the control centre, and a line in the menu bar for the glance.
//
// It does not need extravagant visuals. It needs to remove Terminal from normal ownership:
// turn the Mac on, and this is open, and everything that has to be done to CROOKS OS is a
// button on it.

@main
struct CrooksControlApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var centre = Centre()

    var body: some Scene {
        Window("CROOKS Control", id: Windows.control) {
            ControlCentreView(centre: centre)
        }
        .defaultSize(width: 720, height: 760)
        .windowResizability(.contentMinSize)

        Window("CROOKS Output", id: Windows.output) {
            OutputView(log: centre.log)
        }
        .defaultSize(width: 760, height: 480)

        // The glance, for when the window is behind something. One word and a dot; everything
        // else is a click away in the window, where there is room to read it.
        MenuBarExtra {
            GlanceView(centre: centre)
        } label: {
            HStack(spacing: 4) {
                Image(systemName: symbol(centre.dashboard.lifecycle))
                Text(centre.dashboard.lifecycle.word.capitalized)
            }
        }
        .menuBarExtraStyle(.window)
    }

    private func symbol(_ phase: Lifecycle) -> String {
        switch phase {
        case .online: return "checkmark.circle.fill"
        case .offline: return "moon.circle.fill"
        case .starting, .stopping: return "arrow.triangle.2.circlepath.circle.fill"
        case .error: return "exclamationmark.octagon.fill"
        case .unknown: return "questionmark.circle"
        }
    }
}

enum Windows {
    static let control = "control"
    static let output = "output"
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// Closing the window is not quitting. The whole product promise is that CROOKS Control is
    /// simply THERE — closing the window and finding the app gone would make the owner reopen
    /// it from the Dock every time, which is one more thing to know.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

// MARK: - The control centre

struct ControlCentreView: View {
    @ObservedObject var centre: Centre
    @Environment(\.openWindow) private var openWindow
    @State private var showingDeveloper = false

    /// One second, and it does nothing but let the core's own patience expire. Without it a
    /// START that never comes back would sit on "Starting…" until the next poll, or forever if
    /// the script had stopped answering entirely.
    private let clock = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                DashboardView(dashboard: centre.dashboard) {
                    Task { await centre.refresh(fresh: true) }
                }
                ActionsView(
                    groups: centre.dashboard.groups,
                    missing: centre.dashboard.missingControls
                ) { button in
                    centre.perform(button) { openWindow(id: Windows.output) }
                }
                UpdateView(panel: centre.dashboard.update)
                Footer(centre: centre, showingDeveloper: $showingDeveloper)
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(minWidth: 620, minHeight: 560)
        .background(
            // The ground, warmed at the top by whatever the state is. This is the only place
            // the accent is allowed to touch the whole window, and it is at four per cent.
            ZStack(alignment: .top) {
                Ground.base
                LinearGradient(
                    colors: [centre.accent.opacity(0.10), .clear],
                    startPoint: .top, endPoint: .bottom
                )
                .frame(height: 260)
            }
            .ignoresSafeArea()
        )
        .animation(Motion.settle, value: centre.dashboard.accent)
        .task { centre.begin() }
        .onReceive(clock) { _ in centre.tick() }
        .sheet(isPresented: $showingDeveloper) {
            if let panel = centre.dashboard.developer {
                DeveloperView(panel: panel) { showingDeveloper = false }
            }
        }
        .preferredColorScheme(.dark)
    }
}

struct Footer: View {
    @ObservedObject var centre: Centre
    @Binding var showingDeveloper: Bool
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        HStack(spacing: 14) {
            Toggle("Developer Mode", isOn: $centre.developerMode)
                .toggleStyle(.switch)
                .controlSize(.mini)
                .font(.system(size: 11))
                .foregroundStyle(Ink.tertiary)
            if centre.developerMode {
                Button("Open Developer Mode") { showingDeveloper = true }
                    .buttonStyle(.plain)
                    .font(.system(size: 11)).foregroundStyle(Ink.secondary)
            }
            Spacer()
            Button("Output window") { openWindow(id: Windows.output) }
                .buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(Ink.tertiary)
            Button("CROOKS OS folder…") { centre.chooseFolder() }
                .buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(Ink.tertiary)
            Button("Quit") { NSApp.terminate(nil) }
                .buttonStyle(.plain).font(.system(size: 11)).foregroundStyle(Ink.tertiary)
        }
        .padding(.top, 4)
    }
}

// MARK: - The glance

struct GlanceView: View {
    @ObservedObject var centre: Centre
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Circle().fill(centre.accent).frame(width: 10, height: 10)
                Text(centre.dashboard.headline)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Ink.primary)
            }
            Text(centre.dashboard.explanation)
                .font(.system(size: 11.5)).foregroundStyle(Ink.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 6) {
                Pip(health: centre.dashboard.pad.health)
                Text("CROOKS Pad — " + centre.dashboard.pad.word.lowercased())
                    .font(.system(size: 11)).foregroundStyle(Ink.tertiary)
            }
            Divider().overlay(Glass.lineSubtle)
            Button("Open CROOKS Control") { openWindow(id: Windows.control) }
                .keyboardShortcut(.defaultAction)
        }
        .padding(14)
        .frame(width: 300)
        .background(Ground.one)
    }
}
