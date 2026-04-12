//
//  LocationProvider.swift
//  Jarvis iOS
//
//  Thin CoreLocation wrapper. Used once per WebSocket connect to send
//  the user's current position to the server, which then looks up
//  weather for that location instead of the fixed home city (Kisdorf).
//
//  On first launch iOS will show the system location permission dialog.
//  We request .whenInUse which is sufficient — we don't need background
//  location for the MVP.
//

import Foundation
import CoreLocation

final class LocationProvider: NSObject, CLLocationManagerDelegate {

    static let shared = LocationProvider()

    private let manager = CLLocationManager()
    private var continuation: CheckedContinuation<CLLocation?, Never>?

    override init() {
        super.init()
        manager.delegate = self
        // Kilometer accuracy is plenty — we only need a city-level
        // reading for the weather API, and lower accuracy drains less
        // battery.
        manager.desiredAccuracy = kCLLocationAccuracyKilometer
    }

    /// Returns the user's current location, or nil if permission was
    /// denied or the lookup timed out (5 s budget).
    func currentLocation() async -> CLLocation? {
        // Check / request authorization
        let status = manager.authorizationStatus
        if status == .notDetermined {
            manager.requestWhenInUseAuthorization()
            // Give the permission sheet time to appear and be tapped
            try? await Task.sleep(for: .seconds(3))
        }

        let currentStatus = manager.authorizationStatus
        guard currentStatus == .authorizedWhenInUse ||
              currentStatus == .authorizedAlways
        else {
            print("[jarvis] Location not authorized: \(currentStatus.rawValue)")
            return nil
        }

        return await withCheckedContinuation { (cont: CheckedContinuation<CLLocation?, Never>) in
            self.continuation = cont
            self.manager.requestLocation()

            // Hard 5 s timeout — don't hang the activate greeting
            Task {
                try? await Task.sleep(for: .seconds(5))
                if let pending = self.continuation {
                    self.continuation = nil
                    pending.resume(returning: nil)
                }
            }
        }
    }

    // MARK: - CLLocationManagerDelegate

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        if let location = locations.first, let cont = continuation {
            continuation = nil
            cont.resume(returning: location)
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        print("[jarvis] Location error: \(error.localizedDescription)")
        if let cont = continuation {
            continuation = nil
            cont.resume(returning: nil)
        }
    }
}
