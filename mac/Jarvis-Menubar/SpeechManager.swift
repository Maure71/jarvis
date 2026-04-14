//
//  SpeechManager.swift
//  Jarvis macOS
//
//  Same interface as the iOS SpeechManager but without AVAudioSession
//  (macOS handles audio sessions implicitly).
//

import Foundation
import Combine
import Speech
import AVFoundation

@MainActor
final class SpeechManager: ObservableObject {

    @Published var isListening = false
    @Published var isAuthorized = false

    var onFinalTranscript: ((String) -> Void)?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "de-DE"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()

    private var silenceTimer: Task<Void, Never>?
    private var lastPartialResult: String = ""
    private var hasDelivered = false

    // MARK: - Authorization

    func requestAuthorization() async {
        let speechStatus = await withCheckedContinuation { cont in
            SFSpeechRecognizer.requestAuthorization { status in
                cont.resume(returning: status)
            }
        }
        let micAuthorized = await withCheckedContinuation { cont in
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                cont.resume(returning: granted)
            }
        }
        isAuthorized = (speechStatus == .authorized) && micAuthorized
        if !isAuthorized {
            print("[jarvis] Speech/mic not authorized — speech: \(speechStatus.rawValue), mic: \(micAuthorized)")
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
                        Task { @MainActor in self.finishWithTranscript(text) }
                    } else {
                        Task { @MainActor in
                            self.lastPartialResult = text
                            self.resetSilenceTimer()
                        }
                    }
                }

                if error != nil {
                    Task { @MainActor in
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
    }

    // MARK: - Private

    private func finishWithTranscript(_ text: String) {
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
