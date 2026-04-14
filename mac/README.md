# Jarvis Menu-Bar App (macOS)

Native macOS Menu-Bar-App — im Stil von Zippy. Laeuft als Agent-App
(kein Dock-Icon), mit einem schwebenden Panel das neben dem Cursor
erscheint und einem globalen Hotkey zur Aktivierung.

## Features

- **Menu-Bar-Icon** mit Status-Anzeige (idle / listening / thinking / speaking)
- **Floating Panel** — erscheint neben dem Cursor, schwebt ueber allen Fenstern
- **Globaler Hotkey**: `Cmd+Option+J` toggelt das Panel von ueberall
- **Nutzt denselben Jarvis-Server** wie die iOS-App und die PWA
  (`wss://mac-mini-mario.taile91bf3.ts.net/ws`)
- **Native Spracherkennung** via `SFSpeechRecognizer` + `AVAudioEngine`
- **ElevenLabs TTS** ueber den bestehenden Server-Kanal

## Projekt generieren und bauen

### 1. App-Icon vorbereiten (einmalig)

Speichere dein Quell-Bild (z.B. den ITW-Cartoon) irgendwo ab, z.B.
`~/Downloads/mario-itw.png`. Dann:

```bash
cd mac
./prepare_icon.sh ~/Downloads/mario-itw.png
```

Das Skript schneidet den Kopf aus und generiert alle benoetigten
Icon-Groessen (16-512 px, 1x/2x) + das halbtransparente Panel-Watermark.
Die Assets landen unter `Jarvis-Menubar/Assets.xcassets/`.

Falls der Kopf-Ausschnitt nicht passt, editiere die `CROP_X` / `CROP_Y` /
`CROP_SIZE` Variablen oben im Skript und fuehre es erneut aus.

### 2. Xcode-Projekt generieren und bauen

```bash
cd mac
gem install --user-install xcodeproj   # falls noch nicht installiert
ruby generate_project.rb
open Jarvis-Menubar.xcodeproj
```

In Xcode: Team pruefen (IT Warehouse AG), dann Cmd+R.

## Struktur

```
mac/Jarvis-Menubar/
├── JarvisMenubarApp.swift   # App-Entry, AppDelegate, haelt alle Controller
├── MenuBarController.swift  # NSStatusItem + Context-Menue
├── FloatingPanel.swift      # NSPanel, Cursor-Positionierung, .floating level
├── GlobalHotkey.swift       # Carbon RegisterEventHotKey fuer Cmd+Option+J
├── ContentView.swift        # SwiftUI-View im Panel (Orb + Transcript + Input)
├── OrbView.swift            # Shared mit iOS — gleiche Orb-Animation
├── JarvisClient.swift       # WebSocket-Client + Audio-Playback
├── SpeechManager.swift      # SFSpeechRecognizer-Wrapper
├── Info.plist               # generiert von generate_project.rb
└── Jarvis.entitlements      # generiert: Mic, Network, Sandbox off
```

## Unterschied zur iOS-App

- **Keine AVAudioSession** — macOS managed das implizit, also simpler
- **Kein PushManager / LocationProvider** — macht fuer eine Desktop-App
  keinen Sinn
- **Andere UI**: kompaktes schwebendes Panel statt Fullscreen
- **LSUIElement**: laeuft als Agent-App ohne Dock-Eintrag
