//
//  ScreenCaptureManager.swift
//  Jarvis macOS
//
//  Captures the main display via ScreenCaptureKit (macOS 14+).
//  CGDisplayCreateImage is removed in modern macOS; SCKit is the
//  replacement. Triggers the Screen Recording permission prompt
//  on first use — the user must approve in System Settings →
//  Privacy & Security → Screen Recording, then re-launch the app.
//

import AppKit
import CoreGraphics
import ScreenCaptureKit
import Combine

@MainActor
final class ScreenCaptureManager: ObservableObject {

    /// True when the system has granted Screen Recording permission.
    @Published var isAuthorized: Bool = false

    init() {
        refreshAuthorization()
    }

    /// Check (and implicitly prompt for) Screen Recording permission.
    /// The actual prompt is only shown when capture is attempted —
    /// CGPreflightScreenCaptureAccess just reports the current state.
    func refreshAuthorization() {
        isAuthorized = CGPreflightScreenCaptureAccess()
    }

    /// Request permission explicitly. macOS shows the system dialog
    /// the first time. After granting, the user must re-launch the
    /// app for the change to take effect.
    func requestAuthorization() {
        _ = CGRequestScreenCaptureAccess()
        refreshAuthorization()
    }

    /// Capture the main display via ScreenCaptureKit and return PNG
    /// data. Returns nil on permission failure or other capture errors.
    func captureMainDisplayPNG() async -> Data? {
        do {
            // Discover the available displays. This call is the one
            // that actually triggers the permission prompt the first
            // time — refreshAuthorization() above only reports state.
            let content = try await SCShareableContent.excludingDesktopWindows(
                false,
                onScreenWindowsOnly: true
            )
            guard let display = content.displays.first else {
                print("[jarvis] No displays found")
                return nil
            }

            // Configure capture: native resolution, downscaled later.
            let config = SCStreamConfiguration()
            config.width = display.width
            config.height = display.height
            config.showsCursor = true
            config.scalesToFit = true

            // Capture everything on this display, excluding nothing.
            let filter = SCContentFilter(
                display: display,
                excludingWindows: []
            )

            let cgImage = try await SCScreenshotManager.captureImage(
                contentFilter: filter,
                configuration: config
            )

            // Downscale to roughly 1600px wide for a smaller payload.
            let bitmap = NSBitmapImageRep(cgImage: cgImage)
            let maxWidth: CGFloat = 1600
            let width = CGFloat(cgImage.width)
            if width > maxWidth {
                let scale = maxWidth / width
                let newSize = NSSize(width: width * scale,
                                      height: CGFloat(cgImage.height) * scale)
                let scaled = NSImage(size: newSize)
                scaled.addRepresentation(bitmap)
                scaled.size = newSize
                if let tiff = scaled.tiffRepresentation,
                   let rep = NSBitmapImageRep(data: tiff) {
                    return rep.representation(using: .png, properties: [:])
                }
            }
            return bitmap.representation(using: .png, properties: [:])
        } catch {
            print("[jarvis] Screen capture failed: \(error.localizedDescription)")
            // If the error is permission-related, refresh state so the
            // UI / next call sees isAuthorized == false.
            refreshAuthorization()
            return nil
        }
    }
}
