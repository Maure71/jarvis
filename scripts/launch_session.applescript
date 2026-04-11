-- Jarvis — Window Quadrant Snapper (macOS)
-- Snaps VS Code, Obsidian, Chrome and Music into the four screen quadrants.
-- Uses System Events, so Accessibility permission is required for the app
-- that invokes osascript (Terminal / launchd).
--
-- Layout (quadrants, top-left origin):
--   ┌──────────────┬──────────────┐
--   │   VS Code    │   Obsidian   │
--   ├──────────────┼──────────────┤
--   │    Chrome    │    Music     │
--   └──────────────┴──────────────┘
--
-- Missing apps are tolerated — each process is guarded by "if exists".

-- Read screen bounds from Finder desktop window.
tell application "Finder"
	set screenBounds to bounds of window of desktop
	set screenW to item 3 of screenBounds
	set screenH to item 4 of screenBounds
end tell

set menuBarOffset to 25
set halfW to screenW / 2
set halfH to (screenH - menuBarOffset) / 2

-- Integer casts — System Events rejects floats for position/size.
set halfWi to halfW as integer
set halfHi to halfH as integer
set topY to menuBarOffset
set bottomY to (menuBarOffset + halfHi) as integer

-- Small helper: try to snap a process, swallow errors if app missing.
on snap(procName, px, py, pw, ph)
	tell application "System Events"
		if exists (process procName) then
			try
				tell process procName
					if (count of windows) > 0 then
						set position of front window to {px, py}
						set size of front window to {pw, ph}
					end if
				end tell
			on error errMsg
				log "[jarvis] snap " & procName & " failed: " & errMsg
			end try
		else
			log "[jarvis] snap " & procName & " skipped (not running)"
		end if
	end tell
end snap

-- Snap each quadrant. Process names are what appears in
-- "System Events" -> processes, not the display name.
my snap("Code", 0, topY, halfWi, halfHi)
my snap("Obsidian", halfWi, topY, halfWi, halfHi)
my snap("Google Chrome", 0, bottomY, halfWi, halfHi)
my snap("Music", halfWi, bottomY, halfWi, halfHi)
