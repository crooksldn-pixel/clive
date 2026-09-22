import SwiftUI
import CrooksControlCore

// §5.7: Developer Mode is separate and must not dominate.
//
// It is a sheet, not a section — nothing here is on the first viewport, and turning it on
// does not change the size, the shape or the density of the panel behind it. What it holds is
// everything the app knows, in full: every row the control script sent (not the seven the
// front page shows), the exact argv behind each button, the last failure with its exit code
// and its traceback, the contract version, the port, and the uncommitted files.
//
// One thing is still withheld from it, and it is not negotiable: credentials. Every string
// here has already been through Redaction. Developer Mode is a switch in an app, not a
// clearance (§28).

struct DeveloperView: View {
    let panel: DeveloperPanel
    let dismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Developer Mode").font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Ink.primary)
                Spacer()
                Button("Done", action: dismiss).keyboardShortcut(.defaultAction)
            }
            .padding(16)

            Divider().overlay(Glass.lineSubtle)

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Section("Contract") {
                        Row("document version", "\(panel.contract)")
                        Row("app reads", "\(Contract.understood)")
                        Row("loopback port", panel.port.map(String.init) ?? "not reported")
                    }
                    if let failure = panel.lastFailure {
                        Section("Last failure") {
                            Text(failure)
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundStyle(Signal.bad)
                                .textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    Section("Every row the control script sent") {
                        ForEach(panel.rows) { row in
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Pip(health: row.health)
                                Text(row.key)
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundStyle(Ink.tertiary)
                                    .frame(width: 90, alignment: .leading)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(row.value).font(.system(size: 11)).foregroundStyle(Ink.primary)
                                    if !row.detail.isEmpty {
                                        Text(row.detail).font(.system(size: 10))
                                            .foregroundStyle(Ink.quaternary)
                                    }
                                }
                                Spacer(minLength: 0)
                            }
                        }
                    }
                    if !panel.dirty.isEmpty {
                        Section("Uncommitted files in the CROOKS OS folder") {
                            ForEach(panel.dirty, id: \.self) { path in
                                Text(path).font(.system(size: 11, design: .monospaced))
                                    .foregroundStyle(Signal.warn)
                            }
                        }
                    }
                    Section("The command behind each button") {
                        ForEach(panel.commands, id: \.0) { pair in
                            VStack(alignment: .leading, spacing: 1) {
                                Text(pair.0)
                                    .font(.system(size: 11, weight: .semibold))
                                    .foregroundStyle(Ink.secondary)
                                Text(pair.1.joined(separator: " "))
                                    .font(.system(size: 10, design: .monospaced))
                                    .foregroundStyle(Ink.quaternary)
                                    .textSelection(.enabled)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                }
                .padding(16)
            }
        }
        .frame(width: 560, height: 520)
        .background(Ground.one)
    }

    struct Section<Content: View>: View {
        let title: String
        @ViewBuilder let content: Content

        init(_ title: String, @ViewBuilder content: () -> Content) {
            self.title = title
            self.content = content()
        }

        var body: some View {
            VStack(alignment: .leading, spacing: 6) {
                Text(title.uppercased())
                    .font(.system(size: 9, weight: .bold)).tracking(1.1)
                    .foregroundStyle(Ink.quaternary)
                content
            }
        }
    }

    struct Row: View {
        let caption: String
        let value: String

        init(_ caption: String, _ value: String) {
            self.caption = caption
            self.value = value
        }

        var body: some View {
            HStack(spacing: 8) {
                Text(caption).font(.system(size: 11)).foregroundStyle(Ink.tertiary)
                    .frame(width: 130, alignment: .leading)
                Text(value).font(.system(size: 11, design: .monospaced)).foregroundStyle(Ink.primary)
                Spacer(minLength: 0)
            }
        }
    }
}

/// The window the longer commands print into: the suite, the UI run, a report. Raw output on
/// purpose — this is where a traceback and an exit code belong — with credentials already
/// scrubbed on the way in.
struct OutputView: View {
    @ObservedObject var log: CommandLog

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text(log.title.isEmpty ? "Output" : log.title)
                    .font(.system(size: 14, weight: .semibold)).foregroundStyle(Ink.primary)
                if log.running { ProgressView().controlSize(.small) }
                Spacer()
                if let finished = log.finished {
                    Text(finished == 0 ? "finished" : "finished with \(finished)")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(finished == 0 ? Ink.tertiary : Signal.bad)
                }
                if log.running { Button("Stop") { log.stop() } }
            }
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(Array(log.lines.enumerated()), id: \.offset) { pair in
                            Text(pair.element)
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundStyle(Ink.secondary)
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .id(pair.offset)
                        }
                    }
                    .padding(10)
                }
                .onChange(of: log.lines.count) { count in
                    proxy.scrollTo(count - 1, anchor: .bottom)
                }
            }
            .background(RoundedRectangle(cornerRadius: Radius.control, style: .continuous).fill(Ground.base))
        }
        .padding(16)
        .background(Ground.one)
    }
}
