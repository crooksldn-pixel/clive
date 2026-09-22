import SwiftUI

// The CROOKS visual language, as the tablet already defines it.
//
// These are not colours picked to look like CROOKS. They are web/style.css's own tokens,
// transcribed: the same near-black warm ground, the same five-step white glass ladder, the
// same ok/warn/bad, the same radii and the same easing. The Mac and the pad are one product
// and a man looking from one to the other should not be able to tell they were built by
// different hands.
//
// Anything that is NOT in style.css is not invented here either — the system's own materials
// and type scale do the rest, so the app follows light/dark, Increase Contrast and Reduce
// Motion without a palette of ours to maintain.

enum Ink {
    static let primary = Color(hex: 0xEBE8E0)
    static let secondary = Color(hex: 0xB9B6AE)
    static let tertiary = Color(hex: 0x83827C)
    static let quaternary = Color(hex: 0x7A7A74)
}

enum Ground {
    static let base = Color(hex: 0x07070A)
    static let one = Color(hex: 0x0D0D10)
    static let two = Color(hex: 0x131317)
    static let three = Color(hex: 0x191A1F)
}

enum Glass {
    /// One white, five steps. Every state of every control is a step on this ladder, so
    /// selected, pressed and armed read as "more of the same light" rather than as a
    /// different material.
    static let fill = Color.white.opacity(0.05)
    static let raised = Color.white.opacity(0.075)
    static let strong = Color.white.opacity(0.12)
    static let active = Color.white.opacity(0.16)

    static let lineSubtle = Color.white.opacity(0.10)
    static let lineRest = Color.white.opacity(0.18)
    static let lineActive = Color.white.opacity(0.34)
    static let highlight = Color.white.opacity(0.26)
}

enum Signal {
    static let ok = Color(hex: 0x79C996)
    static let warn = Color(hex: 0xDCB266)
    static let bad = Color(hex: 0xDC7F6C)
    static let okDim = Color(hex: 0x79C996).opacity(0.16)
    static let warnDim = Color(hex: 0xDCB266).opacity(0.16)
    static let badDim = Color(hex: 0xDC7F6C).opacity(0.16)
}

enum Radius {
    static let panel: CGFloat = 20
    static let control: CGFloat = 14
    static let small: CGFloat = 8
    static let pill: CGFloat = 999
}

enum Motion {
    /// --motion-switch, --ease-standard. One duration for a state change, everywhere.
    static let settle = Animation.timingCurve(0.4, 0, 0.2, 1, duration: 0.26)
    static let enter = Animation.timingCurve(0.2, 0.7, 0.2, 1, duration: 0.38)
}

extension Accent {
    var colour: Color {
        switch self {
        case .online: return Signal.ok
        case .testing: return Color(hex: 0x7FA8D8)
        case .caution: return Signal.warn
        case .danger: return Signal.bad
        case .idle: return Ink.tertiary
        }
    }

    var dim: Color { colour.opacity(0.16) }
}

extension Health {
    var colour: Color {
        switch self {
        case .ok: return Signal.ok
        case .bad: return Signal.bad
        case .off: return Ink.quaternary
        // Not reported is drawn as an absence, not as a fault and not as health. It is the
        // only state with no fill at all, so it reads as a gap in the row rather than a dot.
        case .notReported: return Glass.lineRest
        }
    }

    var isFilled: Bool { self != .notReported }
}

extension Color {
    init(hex: UInt32) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: 1
        )
    }
}

/// A card. The one surface in the app, so a panel, a band and a tile are the same material at
/// different sizes rather than three inventions.
struct GlassCard: ViewModifier {
    var raised = false

    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: Radius.panel, style: .continuous)
                    .fill(raised ? Glass.raised : Glass.fill)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Radius.panel, style: .continuous)
                    .strokeBorder(Glass.lineSubtle, lineWidth: 1)
            )
    }
}

extension View {
    func glassCard(raised: Bool = false) -> some View {
        modifier(GlassCard(raised: raised))
    }
}
