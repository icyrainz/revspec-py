# revspec demo recording
# Run from repo root: vhs demo/demo.tape

Output demo/demo.gif
Set Width 1200
Set Height 700
Set FontSize 14
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set Padding 10

# Launch revspec
Type "revspec demo/spec.md"
Sleep 1s
Enter
Sleep 2.5s

# Scroll down — show j/k line navigation
Type "j"
Sleep 150ms
Type "j"
Sleep 150ms
Type "j"
Sleep 150ms
Type "j"
Sleep 150ms
Type "j"
Sleep 800ms

# Half-page jump
Ctrl+D
Sleep 1.2s

# Jump to h3 heading — lands on ### Rate Limiting
Type "]3"
Sleep 1.5s

# === Thread 1: Rate limiting comment ===
Type "c"
Sleep 1.2s
Type "Rate limit of 5/15min is too strict — typos will lock out real users."
Sleep 600ms
Tab
Sleep 1.5s

# Wait for AI reply to appear live, then read it
Sleep 5s

# Normal mode, resolve the thread
Escape
Sleep 800ms
Type "r"
Sleep 1.5s

# === Thread 2: Passkey comment ===
# Jump to passkey section via h3 headings
Type "]3"
Sleep 1s
Type "]3"
Sleep 1s
Type "j"
Sleep 150ms
Type "j"
Sleep 800ms

# Add second comment — close immediately
Type "c"
Sleep 1.2s
Type "Should we support passkey + OAuth combo for enterprise SSO?"
Sleep 600ms
Tab
Sleep 1s
Escape
Sleep 500ms
Escape
Sleep 800ms

# Browse around while AI replies in background
Type "gg"
Sleep 800ms
Ctrl+D
Sleep 800ms
Ctrl+D
Sleep 800ms
Type "j"
Sleep 150ms
Type "j"
Sleep 150ms
Type "j"
Sleep 1s

# Open thread list — AI reply has arrived async (unread marker visible)
Type "t"
Sleep 2s
Type "j"
Sleep 600ms
Type "k"
Sleep 600ms

# Jump to the thread with the unread AI reply — popup opens automatically
Enter
Sleep 3s

# Resolve — auto-closes the popup
Type "r"
Sleep 1.2s

# === Submit for rewrite ===
Type "S"
Sleep 1s

# Spinner shows while AI rewrites the spec
Sleep 4s

# Spec reloads with changes applied
Sleep 2s

# Browse to show the updated spec
Ctrl+D
Sleep 1s
Ctrl+D
Sleep 1.5s

# Quit
Type ":q!"
Enter
Sleep 500ms
