//
//  MenuBarController.swift
//  Jarvis macOS
//
//  Owns the NSStatusItem. Left click toggles panel, right click opens
//  a small context menu.
//

import AppKit
import Combine

@MainActor
final class MenuBarController: NSObject {
    private let statusItem: NSStatusItem
    private let client: JarvisClient
    private let onToggle: () -> Void
    private let onQuit: () -> Void
    private var cancellables: Set<AnyCancellable> = []

    init(client: JarvisClient,
         onToggle: @escaping () -> Void,
         onQuit: @escaping () -> Void) {
        self.client = client
        self.onToggle = onToggle
        self.onQuit = onQuit
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        super.init()

        if let button = statusItem.button {
            button.image = Self.menuBarIcon()
            button.target = self
            button.action = #selector(buttonClicked(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }

        client.$orbState
            .sink { [weak self] state in self?.updateIcon(for: state) }
            .store(in: &cancellables)
    }

    @objc private func buttonClicked(_ sender: NSStatusBarButton) {
        guard let event = NSApp.currentEvent else { onToggle(); return }
        if event.type == .rightMouseUp || event.modifierFlags.contains(.control) {
            showMenu()
        } else {
            onToggle()
        }
    }

    private func showMenu() {
        let menu = NSMenu()
        let toggle = NSMenuItem(title: "Panel ein/aus", action: #selector(toggleAction), keyEquivalent: "j")
        toggle.keyEquivalentModifierMask = [.command, .option]
        toggle.target = self
        menu.addItem(toggle)

        let reconnect = NSMenuItem(title: "Neu verbinden", action: #selector(reconnectAction), keyEquivalent: "")
        reconnect.target = self
        menu.addItem(reconnect)

        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Beenden", action: #selector(quitAction), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)

        statusItem.menu = menu
        statusItem.button?.performClick(nil)
        statusItem.menu = nil
    }

    @objc private func toggleAction()    { onToggle() }
    @objc private func reconnectAction() { client.reconnectIfNeeded() }
    @objc private func quitAction()      { onQuit() }

    private func updateIcon(for state: OrbState) {
        guard let button = statusItem.button else { return }
        // If the custom head asset exists we always use it — colour is
        // driven by the button's content tint so active states tint the
        // icon instead of swapping glyphs.
        if let head = NSImage(named: "jarvis-head") {
            let resized = NSImage(size: NSSize(width: 18, height: 18),
                                   flipped: false) { rect in
                head.draw(in: rect)
                return true
            }
            resized.isTemplate = false
            button.image = resized
            button.contentTintColor = Self.tint(for: state)
            return
        }

        let symbol: String
        switch state {
        case .idle:      symbol = "circle"
        case .listening: symbol = "waveform.circle.fill"
        case .thinking:  symbol = "ellipsis.circle.fill"
        case .speaking:  symbol = "speaker.wave.2.circle.fill"
        }
        button.image = NSImage(systemSymbolName: symbol,
                                accessibilityDescription: "Jarvis \(state.rawValue)")
        button.contentTintColor = Self.tint(for: state)
    }

    static func menuBarIcon() -> NSImage? {
        if let head = NSImage(named: "jarvis-head") {
            let resized = NSImage(size: NSSize(width: 18, height: 18),
                                   flipped: false) { rect in
                head.draw(in: rect)
                return true
            }
            return resized
        }
        return NSImage(systemSymbolName: "circle",
                       accessibilityDescription: "Jarvis")
    }

    static func tint(for state: OrbState) -> NSColor? {
        switch state {
        case .idle:      return nil
        case .listening: return NSColor(red: 0.16, green: 0.42, blue: 0.72, alpha: 1)
        case .thinking:  return NSColor(red: 0.79, green: 0.64, blue: 0.15, alpha: 1)
        case .speaking:  return NSColor(red: 0.15, green: 0.79, blue: 0.42, alpha: 1)
        }
    }
}
