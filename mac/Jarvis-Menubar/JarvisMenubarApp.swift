//
//  JarvisMenubarApp.swift
//  Jarvis macOS Menu Bar App
//
//  Entry point. Runs as a menu-bar accessory (no Dock icon, no main
//  window). Sets up the status item and the floating panel, wires up
//  the global hotkey, and kicks off the WebSocket connection on launch.
//

import SwiftUI
import AppKit

@main
struct JarvisMenubarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        Settings { EmptyView() }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var menuBarController: MenuBarController?
    private var floatingPanel: FloatingPanel?
    private var globalHotkey: GlobalHotkey?
    let client = JarvisClient()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let panel = FloatingPanel(client: client)
        floatingPanel = panel

        menuBarController = MenuBarController(
            client: client,
            onToggle: { [weak self] in self?.togglePanel() },
            onQuit: { NSApp.terminate(nil) }
        )

        // Cmd+Option+J (keyCode 38 = "J")
        globalHotkey = GlobalHotkey(keyCode: 38, modifiers: [.command, .option]) {
            [weak self] in self?.togglePanel()
        }

        client.connect()
    }

    private func togglePanel() {
        guard let panel = floatingPanel else { return }
        if panel.isVisible {
            panel.orderOut(nil)
        } else {
            panel.showNearCursor()
            NSApp.activate(ignoringOtherApps: true)
        }
    }
}
