# RevRem hero demo for the README.
#
# Scripted reconstruction of a run (faithful to real `revrem` output
# formatting) — not a live model-backed capture. The companion
# docs/assets/revrem-demo.sh prints the transcript.
#
# Regenerate (needs: vhs, ttyd, ffmpeg):
#   vhs docs/assets/revrem-demo.tape
# Run from the repository root.

Output docs/assets/revrem-demo.gif

Set Shell bash
Set FontSize 18
Set Width 1080
Set Height 560
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 55ms

# Setup (hidden): clean prompt + alias so the command shown is `revrem ...`
# while the deterministic demo script produces the output.
Hide
Type "export PS1='$ '"
Enter
Type "alias revrem='bash ./docs/assets/revrem-demo.sh'"
Enter
Type "clear"
Enter
Show

Sleep 600ms
Type "revrem --base main --max-iterations 2 --check 'pytest -q'"
Sleep 500ms
Enter
Sleep 9s
