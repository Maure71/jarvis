//
//  JarvisApp.swift
//  Jarvis iOS
//
//  App entry point. Owns the single JarvisClient and PushManager
//  instances for the whole app lifetime. Observes ScenePhase so we
//  can reconnect the WebSocket the moment the user brings Jarvis
//  back to the foreground.
//
//  Also bridges UIApplicationDelegate for APNs device token handling,
//  since SwiftUI has no native API for that.
//

import SwiftUI

@main
struct JarvisApp: App {
    @StateObject private var client = JarvisClient()
    @StateObject private var pushManager = PushManager()
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(client)
                .environmentObject(pushManager)
                .preferredColorScheme(.dark)
                .onAppear {
                    // Hand the push manager to the AppDelegate so it
                    // can forward the device token callback.
                    appDelegate.pushManager = pushManager

                    client.connect()
                    pushManager.requestPermissionAndRegister()
                }
                .onChange(of: scenePhase) { _, newPhase in
                    switch newPhase {
                    case .active:
                        client.reconnectIfNeeded()
                    case .background:
                        break
                    default:
                        break
                    }
                }
        }
    }
}

// MARK: - AppDelegate (for APNs token handling)

class AppDelegate: NSObject, UIApplicationDelegate {

    /// Set by JarvisApp.onAppear — bridges the SwiftUI world to the
    /// UIKit delegate callbacks that APNs requires.
    var pushManager: PushManager?

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        Task { @MainActor in
            pushManager?.didRegisterWithToken(deviceToken)
        }
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        Task { @MainActor in
            pushManager?.didFailToRegister(error)
        }
    }
}
