//
//  ContentView.swift
//  Jarvis iOS
//
//  Main (and only) screen. Layout matches the PWA:
//    - Dark background
//    - Centered orb (tap to toggle listening)
//    - Status text below orb
//    - Scrollable transcript (last N exchanges)
//    - Chat input + send button at the bottom
//

import SwiftUI

struct ContentView: View {
    @EnvironmentObject var client: JarvisClient
    @StateObject private var speech = SpeechManager()

    @State private var chatText = ""
    @FocusState private var chatFocused: Bool

    var body: some View {
        ZStack {
            // Full-screen dark background
            Color(red: 0.04, green: 0.04, blue: 0.06)
                .ignoresSafeArea()

            VStack(spacing: 0) {

                Spacer()

                // ── Orb ──
                OrbView(state: client.orbState)
                    .onTapGesture { handleOrbTap() }
                    .padding(.bottom, 16)

                // ── Status ──
                if !client.statusText.isEmpty {
                    Text(client.statusText)
                        .font(.system(size: 14))
                        .foregroundStyle(.gray)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 24)
                        .padding(.bottom, 8)
                        .transition(.opacity)
                }

                // ── Connection banner ──
                if client.connectionState == .disconnected {
                    Button("Neu verbinden") {
                        client.reconnectIfNeeded()
                    }
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 8)
                    .background(Color.red.opacity(0.7))
                    .clipShape(Capsule())
                    .padding(.bottom, 8)
                }

                Spacer()

                // ── Transcript ──
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 8) {
                            ForEach(client.transcript) { entry in
                                HStack(alignment: .top, spacing: 0) {
                                    Text(entry.role == .user ? "Du: " : "Jarvis: ")
                                        .font(.system(size: 13, weight: .semibold))
                                        .foregroundStyle(
                                            entry.role == .user
                                                ? .gray
                                                : Color(red: 0.29, green: 0.62, blue: 1.0)
                                        )
                                    Text(entry.text)
                                        .font(.system(size: 13))
                                        .foregroundStyle(
                                            entry.role == .user
                                                ? .gray
                                                : Color(red: 0.29, green: 0.62, blue: 1.0)
                                        )
                                }
                                .id(entry.id)
                            }
                        }
                        .padding(.horizontal, 20)
                    }
                    .frame(maxHeight: 180)
                    .onChange(of: client.transcript.count) { _, _ in
                        if let last = client.transcript.last {
                            withAnimation(.easeOut(duration: 0.2)) {
                                proxy.scrollTo(last.id, anchor: .bottom)
                            }
                        }
                    }
                }

                // ── Chat input ──
                HStack(spacing: 8) {
                    TextField("Nachricht an Jarvis...", text: $chatText)
                        .textFieldStyle(.plain)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                        .background(Color(red: 0.10, green: 0.10, blue: 0.13))
                        .clipShape(RoundedRectangle(cornerRadius: 24))
                        .foregroundStyle(.white)
                        .focused($chatFocused)
                        .submitLabel(.send)
                        .onSubmit(sendChat)
                        .onChange(of: chatFocused) { _, focused in
                            if focused && speech.isListening {
                                speech.stopListening()
                                client.orbState = .idle
                            }
                        }

                    Button(action: sendChat) {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(.white)
                            .frame(width: 44, height: 44)
                            .background(
                                chatText.trimmingCharacters(in: .whitespaces).isEmpty
                                    ? Color.gray.opacity(0.3)
                                    : Color(red: 0.10, green: 0.23, blue: 0.36)
                            )
                            .clipShape(Circle())
                    }
                    .disabled(chatText.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 16)
            }
        }
        .onAppear {
            setupSpeech()
        }
    }

    // MARK: - Actions

    private func handleOrbTap() {
        if speech.isListening {
            speech.stopListening()
            client.orbState = .idle
            client.statusText = "Pausiert. Tippen zum Fortsetzen."
        } else if client.orbState == .idle || client.orbState == .listening {
            // Dismiss keyboard if open, then start voice
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
        // Keep keyboard open for quick follow-up
        chatFocused = true
    }

    private func setupSpeech() {
        Task {
            await speech.requestAuthorization()
        }

        // Wire up: when speech produces a final transcript, send it
        speech.onFinalTranscript = { text in
            client.sendSpeech(text)
        }

        // Wire up: when Jarvis finishes speaking, auto-restart listening
        client.onDoneSpeaking = {
            guard speech.isAuthorized else { return }
            // Dismiss keyboard if it was open (e.g. after typed message)
            chatFocused = false
            // Small delay so audio session can switch back to recording
            Task {
                try? await Task.sleep(for: .milliseconds(300))
                speech.startListening()
                client.orbState = .listening
            }
        }
    }
}

#Preview {
    ContentView()
        .environmentObject(JarvisClient())
}
