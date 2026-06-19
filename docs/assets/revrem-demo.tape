# RevRem hero demo for the README.
#
# Scripted reconstruction of a run (faithful to real `revrem` output
# formatting) — not a live model-backed capture. The companion
# docs/assets/revrem-demo.sh prints the transcript.
#
# The command is pre-typed (hidden) before the recording shows, so the GIF's
# first frame ("poster") is the branded command ready to run rather than an
# empty terminal. It then animates the run and rests on the success summary;
# because GIFs loop, both the open and the resting frame are meaningful.
#
# Regenerate (needs: vhs, ttyd, ffmpeg):
#   vhs docs/assets/revrem-demo.tape
# Run from the repository root.

Output docs/assets/revrem-demo.gif

Set Shell bash
Set FontSize 18
Set Width 1080
Set Height 470
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms

# Setup (hidden): clean prompt + alias so the command shown is `revrem ...`
# while the deterministic demo script produces the output. Pre-type the
# command too, so the first visible frame is the ready-to-run command.
Hide
Type "export PS1='$ '"
Enter
Type "alias revrem='bash ./docs/assets/revrem-demo.sh'"
Enter
Type "clear"
Enter
Type "revrem --base main --max-iterations 2 --check \"pytest -q\""
Show

# Poster: hold on the ready command, then run it.
Sleep 1300ms
Enter
Sleep 8s

# Rest on the success summary before the loop restarts.
Sleep 1400ms
