//
//  ContentView.swift
//  Jarvis macOS
//
//  The SwiftUI view hosted inside the FloatingPanel. Layout:
//    - Orb at top (tap to toggle listening)
//    - Status text
//    - Transcript (scrollable)
//    - Chat input
//

import SwiftUI

struct ContentView: View {
    @EnvironmentObject var client: JarvisClient
    @StateObject private var speech = SpeechManager()

    @State private var chatText = ""
    @FocusState private var chatFocused: Bool

    var body: some View {
        ZStack {
            // Translucent blurred background — feels native on macOS.
            VisualEffectView(material: .hudWindow, blendingMode: .behindWindow)
                .ignoresSafeArea()

            // Semi-transparent Jarvis head watermark (optional).
            // Place a file named "jarvis-head.png" in the Assets catalog
            // to activate it. If the asset is missing, this is a no-op.
            if let head = NSImage(named: "jarvis-head") {
                Image(nsImage: head)
                    .resizable()
                    .scaledToFit()
                    .opacity(0.08)
                    .blendMode(.screen)
                    .allowsHitTesting(false)
                    .padding(40)
            }

            VStack(spacing: 0) {
                Spacer(minLength: 20)

                // ── Orb ──
                OrbView(state: client.orbState)
                    .onTapGesture { handleOrbTap() }
                    .padding(.bottom, 12)

                // ── Status ──
                if !client.statusText.isEmpty {
                    Text(client.statusText)
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 16)
                        .padding(.bottom, 6)
                }

                // ── Connection banner ──
                if client.connectionState == .disconnected {
                    Button("Neu verbinden") { client.reconnectIfNeeded() }
                        .buttonStyle(.borderedProminent)
                        .tint(.red)
                        .padding(.bottom, 6)
                }

                // ── Transcript ──
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 8) {
                            ForEach(client.transcript) { entry in
                                HStack(alignment: .top, spacing: 0) {
                                    Text(entry.role == .user ? "Du: " : "Jarvis: ")
                                        .font(.system(size: 12, weight: .semibold))
                                        .foregroundStyle(
                                            entry.role == .user
                                                ? .secondary
                                                : Color(red: 0.29, green: 0.62, blue: 1.0)
                                        )
                                    Text(entry.text)
                                        .font(.system(size: 12))
                                        .foregroundStyle(
                                            entry.role == .user
                                                ? .secondary
                                                : Color(red: 0.29, green: 0.62, blue: 1.0)
                                        )
                                }
                                .id(entry.id)
                            }
                        }
                        .padding(.horizontal, 14)
                    }
                    .onChange(of: client.transcript.count) { _, _ in
                        if let last = client.transcript.last {
                            withAnimation(.easeOut(duration: 0.2)) {
                                proxy.scrollTo(last.id, anchor: .bottom)
                            }
                        }
                    }
                }

                // ── Chat input ──
                HStack(spacing: 6) {
                    TextField("Nachricht an Jarvis...", text: $chatText)
                        .textFieldStyle(.plain)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(Color.black.opacity(0.25))
                        .clipShape(RoundedRectangle(cornerRadius: 18))
                        .focused($chatFocused)
                        .onSubmit(sendChat)
                        .onChange(of: chatFocused) { _, focused in
                            if focused && speech.isListening {
                                speech.stopListening()
                                client.orbState = .idle
                            }
                        }

                    Button(action: sendChat) {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(.white)
                            .frame(width: 30, height: 30)
                            .background(
                                chatText.trimmingCharacters(in: .whitespaces).isEmpty
                                    ? Color.gray.opacity(0.3)
                                    : Color(red: 0.10, green: 0.23, blue: 0.36)
                            )
                            .clipShape(Circle())
                    }
                    .buttonStyle(.plain)
                    .disabled(chatText.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                .padding(.horizontal, 12)
                .padding(.bottom, 12)
            }
        }
        .frame(width: 380, height: 520)
        .onAppear { setupSpeech() }
    }

    // MARK: - Actions

    private func handleOrbTap() {
        if speech.isListening {
            speech.stopListening()
            client.orbState = .idle
            client.statusText = "Pausiert. Tippen zum Fortsetzen."
        } else if client.orbState == .idle || client.orbState == .listening {
            chatFocused = false
            speech.startListening()
            client.orbState = .listening
            client.statusText = ""
        }
    }

    private func sendChat() {
        let trimmed = chatText.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }
        client.sendText(trimmed)
        chatText = ""
        chatFocused = true
    }

    private func setupSpeech() {
        Task { await speech.requestAuthorization() }
        speech.onFinalTranscript = { text in
            client.sendSpeech(text)
        }
        client.onDoneSpeaking = {
            guard speech.isAuthorized else { return }
            chatFocused = false
            Task {
                try? await Task.sleep(for: .milliseconds(300))
                speech.startListening()
                client.orbState = .listening
            }
        }
    }
}

// MARK: - NSVisualEffectView SwiftUI wrapper

struct VisualEffectView: NSViewRepresentable {
    let material: NSVisualEffectView.Material
    let blendingMode: NSVisualEffectView.BlendingMode

    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = material
        view.blendingMode = blendingMode
        view.state = .active
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material = material
        nsView.blendingMode = blendingMode
    }
}
