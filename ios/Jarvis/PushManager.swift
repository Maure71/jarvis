//
//  PushManager.swift
//  Jarvis iOS
//
//  Handles Apple Push Notification (APNs) registration and token
//  forwarding to the Jarvis server. The server stores the device
//  token and can use it to send push notifications later (e.g.
//  "Wallbox fertig", "Pool pH zu niedrig", "Hausakku voll").
//
//  The actual SENDING of push notifications is the server's job —
//  this file only covers the iOS side: requesting permission,
//  extracting the device token, and posting it to a new REST
//  endpoint on the server (/api/push/register).
//
//  Setup checklist (Xcode):
//    1. Target → Signing & Capabilities → + Capability → Push Notifications
//    2. Target → Signing & Capabilities → + Capability → Background Modes
//       → check "Remote notifications"
//    3. Apple Developer Portal → Keys → create an APNs key (.p8)
//       → download once, store on Mini, configure server with:
//         - Key ID
//         - Team ID
//         - .p8 file path
//

import Foundation
import Combine
import UserNotifications
import UIKit

@MainActor
final class PushManager: ObservableObject {

    @Published var isRegistered = false
    @Published var deviceToken: String?

    private let serverHost = "mac-mini-mario.taile91bf3.ts.net"

    /// Request notification permission and register with APNs.
    /// Call this once at app launch (e.g. from JarvisApp.onAppear).
    func requestPermissionAndRegister() {
        UNUserNotificationCenter.current().requestAuthorization(
            options: [.alert, .sound, .badge]
        ) { granted, error in
            if let error {
                print("[jarvis] Push auth error: \(error)")
                return
            }
            guard granted else {
                print("[jarvis] Push permission denied")
                return
            }
            // Trigger APNs registration — this causes
            // application(_:didRegisterForRemoteNotificationsWithDeviceToken:)
            // to fire on the AppDelegate.
            DispatchQueue.main.async {
                UIApplication.shared.registerForRemoteNotifications()
            }
        }
    }

    /// Called from AppDelegate when APNs returns a device token.
    func didRegisterWithToken(_ tokenData: Data) {
        let token = tokenData.map { String(format: "%02x", $0) }.joined()
        self.deviceToken = token
        print("[jarvis] APNs device token: \(token)")

        // Post the token to the Jarvis server so it can send pushes later
        Task {
            await registerTokenWithServer(token)
        }
    }

    /// Called from AppDelegate when APNs registration fails.
    func didFailToRegister(_ error: Error) {
        print("[jarvis] APNs registration failed: \(error)")
    }

    // MARK: - Server registration

    private func registerTokenWithServer(_ token: String) async {
        guard let url = URL(string: "https://\(serverHost)/api/push/register") else { return }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = [
            "device_token": token,
            "device_name": UIDevice.current.name,
            "platform": "ios",
        ]

        guard let httpBody = try? JSONSerialization.data(withJSONObject: body) else { return }
        request.httpBody = httpBody

        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 {
                isRegistered = true
                print("[jarvis] Push token registered with server")
            } else {
                print("[jarvis] Push register failed: \(response)")
            }
        } catch {
            print("[jarvis] Push register error: \(error)")
        }
    }
}
