import SwiftUI
import CrooksControlCore

// The update, which is the one thing in this app that takes two clicks: one to see what is
// coming, one to take it. The SHAs are shown before anything moves, because that is the moment
// the owner decides.
//
// The headline and the sentence are the core's verdict, not this view's reading of the
// document. That matters most in the case that looks like success: an update that moved the
// build and did not come back says UPDATE FAILED here, in red, with ROLL BACK beside it.

struct UpdateView: View {
    let panel: UpdatePanel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text("UPDATE")
                    .font(.system(size: 10, weight: .bold)).tracking(1.2)
                    .foregroundStyle(Ink.quaternary)
                Spacer(minLength: 0)
                Text(panel.headline)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(tint)
            }
            Text(panel.sentence)
                .font(.system(size: 12.5)).foregroundStyle(Ink.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if !panel.stages.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(panel.stages) { stage in
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Text(mark(stage.state))
                                .font(.system(size: 10, weight: .bold, design: .monospaced))
                                .foregroundStyle(colour(stage.state))
                                .frame(width: 34, alignment: .leading)
                            Text(stage.stage)
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundStyle(Ink.tertiary)
                                .frame(width: 64, alignment: .leading)
                            Text(stage.detail)
                                .font(.system(size: 11)).foregroundStyle(Ink.tertiary)
                                .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 0)
                        }
                    }
                }
                .padding(.top, 2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .glassCard()
        .overlay(
            RoundedRectangle(cornerRadius: Radius.panel, style: .continuous)
                .strokeBorder(panel.verdict.isFailure ? Signal.bad.opacity(0.5) : Color.clear, lineWidth: 1)
        )
    }

    private var tint: Color {
        switch panel.verdict {
        case .installed: return Signal.ok
        case .failed: return Signal.bad
        case .available: return Signal.warn
        case .refused: return Signal.warn
        case .upToDate, .notChecked: return Ink.tertiary
        }
    }

    private func mark(_ state: String) -> String {
        switch state {
        case "ok": return "ok"
        case "fail": return "FAIL"
        case "warn": return "warn"
        default: return "—"
        }
    }

    private func colour(_ state: String) -> Color {
        switch state {
        case "ok": return Signal.ok
        case "fail": return Signal.bad
        case "warn": return Signal.warn
        default: return Ink.quaternary
        }
    }
}
