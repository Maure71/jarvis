//
//  OrbView.swift
//  Jarvis iOS
//
//  The glowing, pulsing orb that is Jarvis' face. Matches the
//  look-and-feel of the web frontend's CSS orb (radial gradient +
//  box-shadow) with native SwiftUI animations.
//
//  States:
//    idle      — dim blue, no pulse
//    listening — bright blue, gentle breathe (0.75 s)
//    thinking  — gold/amber, faster pulse (0.5 s)
//    speaking  — green, energetic pulse (0.35 s)
//

import SwiftUI

struct OrbView: View {
    let state: OrbState

    // Animation driver
    @State private var pulsing = false

    var body: some View {
        ZStack {
            // Outer glow (the "box-shadow" equivalent)
            Circle()
                .fill(glowColor.opacity(0.15))
                .frame(width: 220, height: 220)
                .blur(radius: 40)
                .scaleEffect(pulsing ? 1.15 : 1.0)

            // Inner glow
            Circle()
                .fill(glowColor.opacity(0.25))
                .frame(width: 170, height: 170)
                .blur(radius: 20)
                .scaleEffect(pulsing ? 1.1 : 1.0)

            // The orb itself
            Circle()
                .fill(gradient)
                .frame(width: 150, height: 150)
                .shadow(color: glowColor.opacity(0.6), radius: 30)
                .scaleEffect(pulsing ? 1.06 : 1.0)
        }
        .onAppear { updateAnimation() }
        .onChange(of: state) { _, _ in updateAnimation() }
    }

    // MARK: - Appearance per state

    private var gradient: RadialGradient {
        let (inner, outer) = colors
        return RadialGradient(
            colors: [inner, outer],
            center: .init(x: 0.4, y: 0.4),
            startRadius: 10,
            endRadius: 100
        )
    }

    private var colors: (Color, Color) {
        switch state {
        case .idle:
            return (Color(red: 0.10, green: 0.23, blue: 0.36),
                    Color(red: 0.05, green: 0.11, blue: 0.17))
        case .listening:
            return (Color(red: 0.16, green: 0.42, blue: 0.72),
                    Color(red: 0.10, green: 0.23, blue: 0.36))
        case .thinking:
            return (Color(red: 0.79, green: 0.64, blue: 0.15),
                    Color(red: 0.55, green: 0.41, blue: 0.08))
        case .speaking:
            return (Color(red: 0.15, green: 0.79, blue: 0.42),
                    Color(red: 0.08, green: 0.55, blue: 0.24))
        }
    }

    private var glowColor: Color {
        switch state {
        case .idle:      return Color(red: 0.12, green: 0.35, blue: 0.63)
        case .listening: return Color(red: 0.16, green: 0.42, blue: 0.72)
        case .thinking:  return Color(red: 0.79, green: 0.64, blue: 0.15)
        case .speaking:  return Color(red: 0.15, green: 0.79, blue: 0.42)
        }
    }

    // MARK: - Animation

    private func updateAnimation() {
        // Reset
        pulsing = false

        let duration: Double
        switch state {
        case .idle:
            // No pulse for idle — just static dim orb
            return
        case .listening: duration = 0.75
        case .thinking:  duration = 0.5
        case .speaking:  duration = 0.35
        }

        withAnimation(
            .easeInOut(duration: duration)
            .repeatForever(autoreverses: true)
        ) {
            pulsing = true
        }
    }
}

#Preview {
    VStack(spacing: 40) {
        OrbView(state: .idle)
        OrbView(state: .listening)
        OrbView(state: .thinking)
        OrbView(state: .speaking)
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(.black)
}
