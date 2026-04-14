//
//  GlobalHotkey.swift
//  Jarvis macOS
//
//  Registers a system-wide hotkey (Cmd+Option+J) via Carbon's
//  RegisterEventHotKey. Works even when the app isn't frontmost.
//

import AppKit
import Carbon.HIToolbox

final class GlobalHotkey {
    private var hotKeyRef: EventHotKeyRef?
    private let handler: () -> Void
    private static var registry: [UInt32: GlobalHotkey] = [:]
    private static var nextID: UInt32 = 1
    private static var eventHandler: EventHandlerRef?

    init(keyCode: UInt32, modifiers: NSEvent.ModifierFlags, handler: @escaping () -> Void) {
        self.handler = handler

        let id = GlobalHotkey.nextID
        GlobalHotkey.nextID += 1
        GlobalHotkey.registry[id] = self

        GlobalHotkey.installEventHandlerIfNeeded()

        let hotKeyID = EventHotKeyID(signature: OSType(0x4A525653), id: id) // 'JRVS'
        let carbonMods = Self.carbonModifiers(from: modifiers)
        RegisterEventHotKey(
            keyCode,
            carbonMods,
            hotKeyID,
            GetApplicationEventTarget(),
            0,
            &hotKeyRef
        )
    }

    deinit {
        if let ref = hotKeyRef { UnregisterEventHotKey(ref) }
    }

    private static func carbonModifiers(from flags: NSEvent.ModifierFlags) -> UInt32 {
        var mods: UInt32 = 0
        if flags.contains(.command) { mods |= UInt32(cmdKey) }
        if flags.contains(.option)  { mods |= UInt32(optionKey) }
        if flags.contains(.control) { mods |= UInt32(controlKey) }
        if flags.contains(.shift)   { mods |= UInt32(shiftKey) }
        return mods
    }

    private static func installEventHandlerIfNeeded() {
        guard eventHandler == nil else { return }
        var spec = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind: UInt32(kEventHotKeyPressed)
        )
        InstallEventHandler(
            GetApplicationEventTarget(),
            { _, event, _ -> OSStatus in
                var hotKeyID = EventHotKeyID()
                GetEventParameter(
                    event,
                    EventParamName(kEventParamDirectObject),
                    EventParamType(typeEventHotKeyID),
                    nil,
                    MemoryLayout<EventHotKeyID>.size,
                    nil,
                    &hotKeyID
                )
                if let hotkey = GlobalHotkey.registry[hotKeyID.id] {
                    DispatchQueue.main.async { hotkey.handler() }
                }
                return noErr
            },
            1,
            &spec,
            nil,
            &eventHandler
        )
    }
}
