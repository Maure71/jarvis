//
//  FloatingPanel.swift
//  Jarvis macOS
//
//  A borderless NSPanel that floats above other windows and appears
//  next to the cursor (Zippy-style). Hosts the SwiftUI ContentView.
//

import AppKit
import SwiftUI

final class FloatingPanel: NSPanel {
    private let panelSize = NSSize(width: 380, height: 520)

    init(client: JarvisClient) {
        super.init(
            contentRect: NSRect(origin: .zero, size: panelSize),
            styleMask: [.nonactivatingPanel, .titled, .closable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        self.titleVisibility = .hidden
        self.titlebarAppearsTransparent = true
        self.isFloatingPanel = true
        self.level = .floating
        self.hidesOnDeactivate = false
        self.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        self.isMovableByWindowBackground = true
        self.backgroundColor = .clear
        self.hasShadow = true
        self.isOpaque = false

        let hosting = NSHostingView(
            rootView: ContentView().environmentObject(client)
        )
        hosting.wantsLayer = true
        hosting.layer?.cornerRadius = 16
        hosting.layer?.masksToBounds = true
        self.contentView = hosting
    }

    /// Position the panel close to the current mouse cursor, clamped
    /// to the visible frame of the screen containing the cursor.
    func showNearCursor() {
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { NSMouseInRect(mouse, $0.frame, false) }
            ?? NSScreen.main
            ?? NSScreen.screens.first
        guard let visible = screen?.visibleFrame else {
            makeKeyAndOrderFront(nil)
            return
        }

        var origin = NSPoint(x: mouse.x + 20, y: mouse.y - panelSize.height - 20)
        if origin.x + panelSize.width > visible.maxX {
            origin.x = visible.maxX - panelSize.width - 10
        }
        if origin.x < visible.minX { origin.x = visible.minX + 10 }
        if origin.y < visible.minY { origin.y = visible.minY + 10 }
        if origin.y + panelSize.height > visible.maxY {
            origin.y = visible.maxY - panelSize.height - 10
        }

        setFrameOrigin(origin)
        makeKeyAndOrderFront(nil)
    }

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}
