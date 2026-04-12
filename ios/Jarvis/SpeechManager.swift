//
//  SpeechManager.swift
//  Jarvis iOS
//
//  Wraps Apple's SFSpeechRecognizer + AVAudioEngine into a simple
//  start/stop interface. This is the *native* alternative to the
//  flaky webkitSpeechRecognition used by the PWA — it's dramatically
//  more stable on iOS, supports offline recognition on newer devices,
//  and doesn't randomly stop after 60 seconds.
//

import Foundation
import Speech
import AVFoundation

@MainActor
final class SpeechManager: ObservableObject {

    @Published var isListening = false
    @Published var isAuthorized = false

    /// Called with the final transcript when the user stops talking.
    var onFinalTranscript: ((String) -> Void)?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "de-DE"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()

    // Silence timer: if no speech is detected for 2 seconds after we
    // last got a partial result, treat the utterance as final and stop.
    private var silenceTimer: Task<Void, Never>?
    private var lastPartialResult: String = ""

    // Guard against triple-delivery: isFinal, silenceTimer, and error
    // handler can all race to call finishWithTranscript. This flag
    // ensures only the first one actually sends.
    private var hasDelivered = false

    // MARK: - Authorization

    func requestAuthorization() async {
        let status = await withCheckedContinuation { cont in
            SFSpeechRecognizer.requestAuthorization { status in
                cont.resume(returning: status)
            }
        }
        isAuthorized = (status == .authorized)
        if !isAuthorized {
            print("[jarvis] Speech recognition not authorized: \(status.rawValue)")
        }
    }

    // MARK: - Start / Stop

    func startListening() {
        guard !isListening else { return }
        hasDelivered = false
        guard recognizer?.isAvailable == true else {
            print("[jarvis] SFSpeechRecognizer not available")
            return
        }
        guard isAuthorized else {
            print("[jarvis] Speech not authorized")
            return
        }

        do {
            // Re-activate the audio session for recording
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(
                .playAndRecord,
                mode: .measurement,
                options: [.defaultToSpeaker, .allowBluetoothHFP, .duckOthers]
            )
            try audioSession.setActive(true, options: .notifyOthersOnDeactivation)

            recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
            guard let request = recognitionRequest else { return }
            request.shouldReportPartialResults = true

            let inputNode = audioEngine.inputNode
            let recordingFormat = inputNode.outputFormat(forBus: 0)
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) {
                buffer, _ in
                request.append(buffer)
            }

            audioEngine.prepare()
            try audioEngine.start()
            isListening = true
            lastPartialResult = ""

            recognitionTask = recognizer?.recognitionTask(with: request) {
                [weak self] result, error in
                guard let self else { return }

                if let result {
                    let text = result.bestTranscription.formattedString

                    if result.isFinal {
                        Task { @MainActor in
                            self.finishWithTranscript(text)
                        }
                    } else {
                        // Got a partial — reset the silence timer
                        Task { @MainActor in
                            self.lastPartialResult = text
                            self.resetSilenceTimer()
                        }
                    }
                }

                if error != nil {
                    Task { @MainActor in
                        // If we have a partial result, use it
                        if !self.lastPartialResult.isEmpty {
                            self.finishWithTranscript(self.lastPartialResult)
                        } else {
                            self.stopListening()
                        }
                    }
                }
            }
        } catch {
            print("[jarvis] Start listening error: \(error)")
            stopListening()
        }
    }

    func stopListening() {
        guard isListening else { return }
        silenceTimer?.cancel()
        silenceTimer = nil
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionRequest = nil
        recognitionTask?.cancel()
        recognitionTask = nil
        isListening = false
        lastPartialResult = ""

        // Switch audio session back to playback mode
        do {
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(
                .playAndRecord,
                mode: .voiceChat,
                options: [.defaultToSpeaker, .allowBluetoothHFP]
            )
        } catch {
            print("[jarvis] Audio session reconfigure error: \(error)")
        }
    }

    // MARK: - Private

    private func finishWithTranscript(_ text: String) {
        // Guard: isFinal, silenceTimer, and error handler can all race
        // here. Only the first caller actually delivers the transcript.
        guard !hasDelivered else { return }
        hasDelivered = true
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        stopListening()
        if !trimmed.isEmpty {
            onFinalTranscript?(trimmed)
        }
    }

    private func resetSilenceTimer() {
        silenceTimer?.cancel()
        silenceTimer = Task {
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled else { return }
            if !self.lastPartialResult.isEmpty {
                self.finishWithTranscript(self.lastPartialResult)
            }
        }
    }
}
