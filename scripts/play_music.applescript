-- Jarvis — Apple Music Wake-Up
-- Starts Apple Music with AC/DC megahits at 30% volume, shuffled.
--
-- Strategy:
--   1. Launch Music
--   2. Set app volume (sound volume) to 30%
--   3. Try playing playlist "Jarvis Wake-Up" (user should create this once
--      by saving AC/DC Essentials from Apple Music into their library)
--   4. Fallback: shuffle all AC/DC tracks in the library
--   5. Final fallback: just log and give up (no crash)
--
-- Note: AppleScript has no official access to the Apple Music *streaming*
-- catalog — only to what's in the user's library. The one-time setup is:
-- "AC/DC Essentials" playlist -> Add to Library -> rename to "Jarvis Wake-Up".

set playlistName to "Jarvis Wake-Up"
set fallbackArtist to "AC/DC"
set targetVolume to 30

tell application "Music"
	activate
	-- App-level sound volume (0-100). Separate from system volume.
	set sound volume to targetVolume
	set shuffle enabled to true

	try
		-- Primary: play the named playlist
		play playlist playlistName
		log "[jarvis] Playing playlist '" & playlistName & "'"
	on error errPlaylist
		log "[jarvis] Playlist '" & playlistName & "' not found: " & errPlaylist
		try
			-- Fallback: play any track by AC/DC in the library, then
			-- Music will continue with shuffled library tracks by that artist.
			set acdcTracks to (every track of library playlist 1 whose artist is fallbackArtist)
			if (count of acdcTracks) is 0 then
				error "No AC/DC tracks in library"
			end if
			play (item 1 of acdcTracks)
			log "[jarvis] Playing " & (count of acdcTracks) & " AC/DC library tracks shuffled"
		on error errFallback
			log "[jarvis] AC/DC fallback failed: " & errFallback
			log "[jarvis] One-time setup needed: add 'AC/DC Essentials' from Apple Music to your library and rename the playlist to 'Jarvis Wake-Up'."
		end try
	end try
end tell
