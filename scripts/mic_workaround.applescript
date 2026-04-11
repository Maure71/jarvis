-- Jarvis — Mic Workaround
--
-- Chrome/WebKit require a user gesture before webkitSpeechRecognition
-- will start and before audio autoplay is allowed. After the clap-trigger
-- auto-launch sequence (scripts/launch_session.sh → open Chrome with the
-- Jarvis UI), nobody has clicked yet, so the microphone stays silent
-- until Mario does it manually.
--
-- Strategy: send BOTH a Tab keystroke and a click into Chrome's front
-- window. frontend/main.js registers a one-shot firstGesture listener
-- on the document that starts listening on the first click OR keydown.
--
--   1. Tab keystroke — goes to the focused element (the Chrome webview
--      after activation), reliably reaches the page's document-level
--      keydown listener. This is the PRIMARY trigger for starting the
--      microphone, because it doesn't depend on window geometry.
--
--   2. Mouse click at 75% window height — lands safely inside the page
--      content area (not in Chrome's toolbar/URL bar). This satisfies
--      the audio-replay click handler in main.js playNext() so the
--      greeting audio plays automatically.
--
-- Requirements:
--   - Accessibility permission for whatever runs osascript (Terminal,
--     launchd helper, etc.) — already required for launch_session.applescript
--   - Chrome must be frontmost. We activate it explicitly first.

tell application "Google Chrome" to activate
delay 0.5

tell application "System Events"
    -- Primary: Tab keystroke → document keydown → firstGesture → startListening()
    -- key code 48 = Tab. Harmless in an empty page (just moves focus),
    -- and counts as a genuine user gesture in Chrome.
    key code 48
    delay 0.1

    -- Secondary: click deep inside the page area to replay greeting audio.
    tell process "Google Chrome"
        if (count of windows) is 0 then return
        set _win to front window
        set _pos to position of _win
        set _sz to size of _win
        set cx to (item 1 of _pos) + ((item 1 of _sz) div 2)
        -- 75% down the window — avoids tab bar, URL bar, bookmarks bar
        -- and any permission infobar at the top.
        set cy to (item 2 of _pos) + ((item 2 of _sz) * 3 div 4)
        click at {cx, cy}
    end tell
end tell
