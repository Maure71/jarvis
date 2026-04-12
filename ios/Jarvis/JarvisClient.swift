//
//  JarvisClient.swift
//  Jarvis iOS
//
//  Central hub: owns the WebSocket connection, manages audio playback
//  queue, publishes UI state (@Published) so SwiftUI views react
//  automatically. Designed as a single ObservableObject that lives for
//  the entire app lifetime (owned by JarvisApp).
//

import Foundation
import AVFoundation
import Combine

// MARK: - Types

enum OrbState: String {
    case idle, listening, thinking, speaking
}

enum ConnectionState {
    case disconnected, connecting, connected
}

struct TranscriptEntry: Identifiable {
    let id = UUID()
    let role: Role
    let text: String
    let timestamp = Date()
    enum Role { case user, jarvis }
}

// MARK: - Client

@MainActor
final class JarvisClient: NSObject, ObservableObject {

    // Published state — drives all SwiftUI updates
    @Published var connectionState: ConnectionState = .disconnected
    @Published var orbState: OrbState = .idle
    @Published var transcript: [TranscriptEntry] = []
    @Published var statusText: String = ""

    // Tailscale MagicDNS hostname. Real Let's Encrypt cert, so ATS is
    // happy out of the box — no exception domains needed.
    private let serverHost = "mac-mini-mario.taile91bf3.ts.net"

    private var webSocket: URLSessionWebSocketTask?
    private var session: URLSession!

    // Audio playback queue — chunks arrive base64-encoded, we decode
    // and play them sequentially via AVAudioPlayer.
    private var audioQueue: [Data] = []
    private var audioPlayer: AVAudioPlayer?
    private var isPlaying = false

    // Callback: speech manager listens for "done speaking" to auto-
    // restart listening.
    var onDoneSpeaking: (() -> Void)?

    override init() {
        super.init()
        let config = URLSessionConfiguration.default
        config.waitsForConnectivity = true
        self.session = URLSession(configuration: config)
        configureAudioSession()
    }

    // MARK: - Audio Session

    private func configureAudioSession() {
        do {
            let s = AVAudioSession.sharedInstance()
            // .playAndRecord so we can play TTS AND record mic in the
            // same session. .defaultToSpeaker so audio doesn't route to
            // the earpiece. .allowBluetoothHFP for AirPods.
            try s.setCategory(
                .playAndRecord,
                mode: .voiceChat,
                options: [.defaultToSpeaker, .allowBluetoothHFP]
            )
            try s.setActive(true)
        } catch {
            print("[jarvis] Audio session setup failed: \(error)")
        }
    }

    // MARK: - Connection lifecycle

    func connect() {
        guard connectionState == .disconnected else { return }
        connectionState = .connecting
        statusText = "Verbinde mit Jarvis..."

        guard let url = URL(string: "wss://\(serverHost)/ws") else { return }
        let task = session.webSocketTask(with: url)
        self.webSocket = task
        task.resume()

        // Kick off the receive loop
        receiveLoop()

        // Small delay so the socket has time to finish the TLS
        // handshake before we start sending messages.
        Task {
            try? await Task.sleep(for: .milliseconds(300))
            guard task.state == .running else {
                handleDisconnect()
                return
            }
            self.connectionState = .connected

            // Send GPS location first (for weather override), then
            // the activate greeting.
            await sendLocationIfAvailable()
            send(["text": "Jarvis activate"])
            orbState = .thinking
            statusText = "Jarvis denkt nach..."
        }
    }

    func reconnectIfNeeded() {
        if connectionState != .connected {
            disconnect()
            connect()
        }
    }

    func disconnect() {
        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil
        connectionState = .disconnected
        isPlaying = false
        audioQueue.removeAll()
    }

    // MARK: - Receive loop

    private func receiveLoop() {
        webSocket?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let message):
                Task { @MainActor in
                    self.handleMessage(message)
                    self.receiveLoop()   // keep listening
                }
            case .failure(let error):
                print("[jarvis] WS receive error: \(error)")
                Task { @MainActor in self.handleDisconnect() }
            }
        }
    }

    private func handleMessage(_ message: URLSessionWebSocketTask.Message) {
        guard case .string(let text) = message,
              let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = json["type"] as? String
        else { return }

        switch type {
        case "response":
            let replyText = json["text"] as? String ?? ""
            let audioB64  = json["audio"] as? String ?? ""

            if !replyText.isEmpty {
                transcript.append(.init(role: .jarvis, text: replyText))
            }

            if !audioB64.isEmpty, let audioData = Data(base64Encoded: audioB64) {
                queueAudio(audioData)
            } else if orbState == .thinking {
                // Server sent a text-only response (no audio) — go idle
                orbState = .idle
                statusText = ""
                onDoneSpeaking?()
            }

        case "status":
            statusText = json["text"] as? String ?? ""

        default:
            break
        }
    }

    private func handleDisconnect() {
        connectionState = .disconnected
        orbState = .idle
        statusText = "Verbindung verloren..."

        // Auto-reconnect after a short delay
        Task {
            try? await Task.sleep(for: .seconds(3))
            if connectionState == .disconnected {
                connect()
            }
        }
    }

    // MARK: - Sending

    func send(_ payload: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let string = String(data: data, encoding: .utf8)
        else { return }
        webSocket?.send(.string(string)) { error in
            if let error { print("[jarvis] WS send error: \(error)") }
        }
    }

    func sendText(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        transcript.append(.init(role: .user, text: trimmed))
        orbState = .thinking
        statusText = "Jarvis denkt nach..."
        send(["text": trimmed])
    }

    func sendSpeech(_ text: String) {
        // Same as sendText but caller is SpeechManager, so we know the
        // mic was active. Just delegates to sendText.
        sendText(text)
    }

    // MARK: - Location

    private func sendLocationIfAvailable() async {
        guard let location = await LocationProvider.shared.currentLocation() else { return }
        send([
            "type": "location",
            "lat": location.coordinate.latitude,
            "lon": location.coordinate.longitude,
        ])
        print("[jarvis] Location sent: \(location.coordinate.latitude), \(location.coordinate.longitude)")
    }

    // MARK: - Audio playback queue

    private func queueAudio(_ data: Data) {
        audioQueue.append(data)
        if !isPlaying { playNext() }
    }

    private func playNext() {
        guard !audioQueue.isEmpty else {
            isPlaying = false
            orbState = .idle
            statusText = ""
            onDoneSpeaking?()
            return
        }

        isPlaying = true
        orbState = .speaking
        statusText = ""

        let chunk = audioQueue.removeFirst()
        do {
            audioPlayer = try AVAudioPlayer(data: chunk)
            audioPlayer?.delegate = self
            audioPlayer?.play()
        } catch {
            print("[jarvis] Audio play error: \(error)")
            playNext()
        }
    }
}

// MARK: - AVAudioPlayerDelegate

extension JarvisClient: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in self.playNext() }
    }
}
