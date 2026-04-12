# Jarvis iOS App

Native SwiftUI-App für iPhone. Verbindet sich per WebSocket mit dem
Jarvis-Server auf dem Mac Mini über Tailscale.

## Voraussetzungen

- Xcode 15+ (macOS Sonoma oder neuer)
- Apple Developer Program Mitgliedschaft (99 €/Jahr) — für Push
  Notifications und Zertifikate die länger als 7 Tage halten
- iPhone mit iOS 17+
- Tailscale auf dem iPhone installiert + eingeloggt

## Xcode-Projekt erstellen

Da `.xcodeproj`-Dateien nicht sinnvoll in Git versioniert werden
können, erstellst du das Projekt einmalig in Xcode:

### 1. Neues Projekt

1. Xcode → **File → New → Project**
2. **iOS → App** auswählen → Next
3. Einstellungen:
   - **Product Name**: `Jarvis`
   - **Team**: Dein Apple Developer Team
   - **Organization Identifier**: `com.pustan` (oder was du willst)
   - **Interface**: SwiftUI
   - **Language**: Swift
   - **Storage**: None
   - **Testing System**: None (für MVP egal)
4. **Save location**: `~/code/jarvis/ios/` → Create
   - Xcode erstellt `~/code/jarvis/ios/Jarvis/Jarvis.xcodeproj`

### 2. Auto-generierte Dateien ersetzen

Xcode hat eigene `JarvisApp.swift` und `ContentView.swift` generiert.
**Lösche diese** und ersetze sie:

1. Im Xcode Project Navigator: rechtsklick auf die auto-generierten
   `JarvisApp.swift`, `ContentView.swift` → **Delete → Move to Trash**
2. Rechtsklick auf den `Jarvis`-Ordner → **Add Files to "Jarvis"**
3. Navigiere zu `~/code/jarvis/ios/Jarvis/` und wähle ALLE `.swift`-
   Dateien aus:
   - `JarvisApp.swift`
   - `ContentView.swift`
   - `JarvisClient.swift`
   - `SpeechManager.swift`
   - `LocationProvider.swift`
   - `OrbView.swift`
   - `PushManager.swift`
4. Checkbox: **Copy items if needed** — NICHT ankreuzen (Dateien
   liegen bereits im richtigen Ordner)
5. **Add**

### 3. Info.plist — Berechtigungen

Target → **Info** Tab → Custom iOS Target Properties. Füge hinzu:

| Key | Value |
|-----|-------|
| `NSMicrophoneUsageDescription` | Jarvis nutzt das Mikrofon um Ihre Sprachbefehle zu erkennen. |
| `NSSpeechRecognitionUsageDescription` | Jarvis nutzt Apple Spracherkennung um Ihre Befehle zu verstehen. |
| `NSLocationWhenInUseUsageDescription` | Jarvis nutzt Ihren Standort um aktuelles Wetter für Ihre Position anzuzeigen. |

### 4. Capabilities

Target → **Signing & Capabilities** → **+ Capability**:

1. **Push Notifications** — aktiviert APNs
2. **Background Modes** → Checkbox: **Remote notifications**

### 5. Deployment Target

Target → **General** → **Minimum Deployments**: `iOS 17.0`

### 6. Build & Run

1. iPhone per Kabel anschließen (oder drahtlos wenn bereits gepairt)
2. Oben in Xcode dein iPhone als Zielgerät auswählen
3. **⌘R** (Run)
4. Beim ersten Start: auf dem iPhone unter
   **Einstellungen → Allgemein → VPN & Geräteverwaltung** dem
   Developer-Zertifikat vertrauen

## APNs Key (für Push Notifications)

Damit der Server Push-Notifications senden kann, brauchst du einen
APNs Authentication Key:

1. https://developer.apple.com/account/resources/authkeys/list
2. **Create a Key** → Name: `Jarvis APNs` → Checkbox: **Apple Push
   Notifications service (APNs)** → Continue → Register → Download
3. Du bekommst eine `AuthKey_XXXXXXXXXX.p8` Datei — **einmalig
   downloadbar!** Sicher aufbewahren.
4. Notiere:
   - **Key ID**: steht auf der Key-Seite (10 Zeichen)
   - **Team ID**: steht unter
     https://developer.apple.com/account → Membership Details

Diese drei Werte (Key-Datei, Key ID, Team ID) kommen später in die
Server-Konfiguration.

## Architektur

```
JarvisApp.swift        — @main, ScenePhase, AppDelegate bridge
ContentView.swift      — UI: Orb + Status + Transcript + Chat Input
OrbView.swift          — Animated orb with state-based colors/pulse
JarvisClient.swift     — WebSocket, audio playback, @Published state
SpeechManager.swift    — SFSpeechRecognizer + AVAudioEngine
LocationProvider.swift — CoreLocation → lat/lon for weather override
PushManager.swift      — APNs registration + token forwarding
```

## Protokoll

Identisch zum Web-Frontend:

```json
// Client → Server
{"text": "Jarvis activate"}
{"text": "Wie ist das Wetter?"}
{"type": "location", "lat": 53.78, "lon": 9.97}

// Server → Client
{"type": "response", "text": "...", "audio": "<base64-mp3>"}
{"type": "status", "text": "Jarvis denkt nach..."}
```
