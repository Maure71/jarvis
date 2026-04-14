//
//  OrbView.swift
//  Jarvis macOS
//
//  Shared with iOS — identical SwiftUI view. States: idle, listening,
//  thinking, speaking.
//

import SwiftUI

struct OrbView: View {
    let state: OrbState
    @State private var pulsing = false

    var body: some View {
        ZStack {
            Circle()
                .fill(glowColor.opacity(0.15))
                .frame(width: 180, height: 180)
                .blur(radius: 30)
                .scaleEffect(pulsing ? 1.15 : 1.0)
            Circle()
                .fill(glowColor.opacity(0.25))
                .frame(width: 140, height: 140)
                .blur(radius: 16)
                .scaleEffect(pulsing ? 1.1 : 1.0)
            Circle()
                .fill(gradient)
                .frame(width: 120, height: 120)
                .shadow(color: glowColor.opacity(0.6), radius: 24)
                .scaleEffect(pulsing ? 1.06 : 1.0)
        }
        .onAppear { updateAnimation() }
        .onChange(of: state) { _, _ in updateAnimation() }
    }

    private var gradient: RadialGradient {
        let (inner, outer) = colors
        return RadialGradient(
            colors: [inner, outer],
            center: .init(x: 0.4, y: 0.4),
            startRadius: 10,
            endRadius: 80
        )
    }

    private var colors: (Color, Color) {
        switch state {
        case .idle:      return (Color(red: 0.10, green: 0.23, blue: 0.36),
                                 Color(red: 0.05, green: 0.11, blue: 0.17))
        case .listening: return (Color(red: 0.16, green: 0.42, blue: 0.72),
                                 Color(red: 0.10, green: 0.23, blue: 0.36))
        case .thinking:  return (Color(red: 0.79, green: 0.64, blue: 0.15),
                                 Color(red: 0.55, green: 0.41, blue: 0.08))
        case .speaking:  return (Color(red: 0.15, green: 0.79, blue: 0.42),
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

    private func updateAnimation() {
        pulsing = false
        let duration: Double
        switch state {
        case .idle: return
        case .listening: duration = 0.75
        case .thinking:  duration = 0.5
        case .speaking:  duration = 0.35
        }
        withAnimation(.easeInOut(duration: duration).repeatForever(autoreverses: true)) {
            pulsing = true
        }
    }
}
