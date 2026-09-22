import SwiftUI
import CrooksControlCore

// The first viewport. It answers five questions and it does not ask anything of the man
// reading it:
//
//     IS CROOKS OS RUNNING?     one word, at forty-two point, with a lit ring behind it
//     IS THE TABLET CONNECTED?  a card of its own, because it is half the product
//     ARE SERVICES HEALTHY?     seven pips on one line
//     WHAT VERSION?             one quiet line at the foot
//     IS A TEST SESSION ACTIVE? a band that only exists while one is
//
// There is not a decision in this file. Everything it draws is a field of `Dashboard`.

struct DashboardView: View {
    let dashboard: Dashboard
    let refresh: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            StateBlock(dashboard: dashboard, refresh: refresh)
            if dashboard.session.active { SessionBandView(session: dashboard.session) }
            if let notice = dashboard.notice { NoticeView(notice: notice) }
            HStack(alignment: .top, spacing: 12) {
                PadCardView(pad: dashboard.pad)
                ServicesCard(services: dashboard.services)
            }
            IdentityFooter(identity: dashboard.identity)
        }
    }
}

/// The one thing a glance from the other side of the shop has to land on.
struct StateBlock: View {
    let dashboard: Dashboard
    let refresh: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 18) {
            Halo(accent: dashboard.accent, working: dashboard.lifecycle.isTransitional)
            VStack(alignment: .leading, spacing: 6) {
                Text(dashboard.headline)
                    .font(.system(size: 30, weight: .semibold, design: .rounded))
                    .foregroundStyle(Ink.primary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                Text(dashboard.explanation)
                    .font(.system(size: 13))
                    .foregroundStyle(Ink.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let busy = dashboard.busy {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.small)
                        Text(busy + "…").font(.system(size: 12)).foregroundStyle(Ink.tertiary)
                    }
                }
            }
            Spacer(minLength: 8)
            Button(action: refresh) {
                Image(systemName: "arrow.clockwise").font(.system(size: 13, weight: .medium))
            }
            .buttonStyle(.plain)
            .foregroundStyle(Ink.tertiary)
            .help("Read CROOKS OS again now")
        }
        .padding(20)
        .glassCard(raised: true)
        .animation(Motion.settle, value: dashboard.lifecycle)
    }
}

/// The lit ring. Subtle animation (§5.8): it breathes only while something is genuinely in
/// flight, so a still ring means a settled system rather than a stopped app.
struct Halo: View {
    let accent: Accent
    let working: Bool
    @State private var pulse = false

    var body: some View {
        ZStack {
            Circle().fill(accent.colour.opacity(0.14)).frame(width: 62, height: 62)
            Circle().strokeBorder(accent.colour.opacity(working && pulse ? 0.9 : 0.45), lineWidth: 2)
                .frame(width: 62, height: 62)
            Circle().fill(accent.colour).frame(width: 16, height: 16)
                .shadow(color: accent.colour.opacity(0.55), radius: 10)
        }
        .scaleEffect(working && pulse ? 1.04 : 1.0)
        .animation(working ? Motion.settle.repeatForever(autoreverses: true) : Motion.settle, value: pulse)
        .onAppear { pulse = working }
        .onChange(of: working) { now in pulse = now }
    }
}

struct SessionBandView: View {
    let session: SessionBand

    var body: some View {
        HStack(spacing: 10) {
            Circle().fill(Accent.testing.colour).frame(width: 8, height: 8)
            Text("RECORDING")
                .font(.system(size: 11, weight: .bold)).tracking(1.1)
                .foregroundStyle(Accent.testing.colour)
            Text(session.name.isEmpty ? session.id : session.name)
                .font(.system(size: 12)).foregroundStyle(Ink.secondary)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: Radius.control, style: .continuous)
                .fill(Accent.testing.dim)
        )
        .transition(.opacity)
    }
}

struct NoticeView: View {
    let notice: Notice

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: symbol).foregroundStyle(tint).font(.system(size: 13, weight: .semibold))
            VStack(alignment: .leading, spacing: 3) {
                Text(notice.text).font(.system(size: 12.5)).foregroundStyle(Ink.primary)
                    .fixedSize(horizontal: false, vertical: true)
                if let fix = notice.fix {
                    Text(fix).font(.system(size: 12)).foregroundStyle(Ink.tertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: Radius.control, style: .continuous).fill(tint.opacity(0.13))
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.control, style: .continuous)
                .strokeBorder(tint.opacity(0.35), lineWidth: 1)
        )
    }

    private var tint: Color {
        switch notice.tone {
        case .info: return Ink.secondary
        case .caution: return Signal.warn
        case .danger: return Signal.bad
        }
    }

    private var symbol: String {
        switch notice.tone {
        case .info: return "info.circle.fill"
        case .caution: return "exclamationmark.triangle.fill"
        case .danger: return "exclamationmark.octagon.fill"
        }
    }
}

struct PadCardView: View {
    let pad: PadCard

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("CROOKS PAD")
                .font(.system(size: 10, weight: .bold)).tracking(1.2)
                .foregroundStyle(Ink.quaternary)
            HStack(spacing: 8) {
                Pip(health: pad.health)
                Text(pad.word)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(pad.health == .ok ? Ink.primary : Ink.secondary)
            }
            Text(pad.detail)
                .font(.system(size: 11.5)).foregroundStyle(Ink.tertiary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .frame(width: 220, alignment: .leading)
        .padding(16)
        .glassCard()
    }
}

struct ServicesCard: View {
    let services: [ServiceTile]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("SERVICES")
                .font(.system(size: 10, weight: .bold)).tracking(1.2)
                .foregroundStyle(Ink.quaternary)
            ForEach(services) { service in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Pip(health: service.health)
                    Text(service.name)
                        .font(.system(size: 12, weight: service.essential ? .semibold : .regular))
                        .foregroundStyle(Ink.primary)
                        .frame(width: 76, alignment: .leading)
                    Text(service.value)
                        .font(.system(size: 11.5))
                        .foregroundStyle(service.health == .bad ? Signal.bad : Ink.tertiary)
                        .lineLimit(1).truncationMode(.tail)
                    Spacer(minLength: 0)
                }
                .help(service.detail.isEmpty ? service.value : "\(service.value)\n\(service.detail)")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .glassCard()
    }
}

/// The dot. `notReported` is drawn hollow on purpose: an absence must not look like a state.
struct Pip: View {
    let health: Health

    var body: some View {
        Group {
            if health.isFilled {
                Circle().fill(health.colour)
            } else {
                Circle().strokeBorder(health.colour, lineWidth: 1)
            }
        }
        .frame(width: 8, height: 8)
    }
}

struct IdentityFooter: View {
    let identity: IdentityLine

    var body: some View {
        HStack(spacing: 18) {
            Labelled("BUILD", identity.runningBuild)
            Labelled("CHECKOUT", identity.checkout)
            Labelled("UPTIME", identity.uptime)
            Labelled("LAST GOOD", identity.lastKnownGood)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 4)
    }

    struct Labelled: View {
        let caption: String
        let value: String

        init(_ caption: String, _ value: String) {
            self.caption = caption
            self.value = value
        }

        var body: some View {
            VStack(alignment: .leading, spacing: 2) {
                Text(caption)
                    .font(.system(size: 9, weight: .bold)).tracking(1.0)
                    .foregroundStyle(Ink.quaternary)
                Text(value)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(Ink.secondary)
                    .lineLimit(1).truncationMode(.middle)
            }
            .help(value)
        }
    }
}
