//
//  ScreenCaptureManager.swift
//  Jarvis macOS
//
//  Captures the main display via CGDisplayCreateImage. Triggers the
//  Screen Recording permission prompt on first use (the user has to
//  approve once in System Settings → Privacy & Security → Screen
//  Recording, then re-launch the app).
//

import AppKit
import CoreGraphics
import Combine

@MainActor
final class ScreenCaptureManager: ObservableObject {

    /// True when the system has granted Screen Recording permission.
    @Published var isAuthorized: Bool = false

    init() {
        refreshAuthorization()
    }

    /// Check (and implicitly prompt for) Screen Recording permission.
    /// macOS shows the prompt the first time CGDisplayCreateImage is
    /// called on the main display. After granting, the user must
    /// re-launch the app before it takes effect.
    func refreshAuthorization() {
        // Use CGPreflightScreenCaptureAccess if available (macOS 10.15+);
        // otherwise probe by attempting a tiny capture.
        if #available(macOS 11.0, *) {
            isAuthorized = CGPreflightScreenCaptureAccess()
        } else {
            isAuthorized = (CGDisplayCreateImage(CGMainDisplayID()) != nil)
        }
    }

    /// Request permission explicitly. Triggers the system prompt on
    /// first call. No-op if already authorized.
    func requestAuthorization() {
        if #available(macOS 11.0, *) {
            _ = CGRequestScreenCaptureAccess()
        } else {
            _ = CGDisplayCreateImage(CGMainDisplayID())
        }
        refreshAuthorization()
    }

    /// Capture the main display and return PNG data, or nil on error.
    /// Runs synchronously — keep call sites off the main render path.
    func captureMainDisplayPNG() -> Data? {
        let displayID = CGMainDisplayID()
        guard let image = CGDisplayCreateImage(displayID) else {
            print("[jarvis] Screen capture failed — is Screen Recording permission granted?")
            return nil
        }
        let bitmap = NSBitmapImageRep(cgImage: image)
        // Downscale to roughly 1600px wide to keep the payload small.
        let maxWidth: CGFloat = 1600
        let width = CGFloat(image.width)
        if width > maxWidth {
            let scale = maxWidth / width
            let newSize = NSSize(width: width * scale,
                                  height: CGFloat(image.height) * scale)
            let scaled = NSImage(size: newSize)
            scaled.addRepresentation(bitmap)
            scaled.size = newSize
            if let tiff = scaled.tiffRepresentation,
               let rep = NSBitmapImageRep(data: tiff) {
                return rep.representation(using: .png, properties: [:])
            }
        }
        return bitmap.representation(using: .png, properties: [:])
    }
}
