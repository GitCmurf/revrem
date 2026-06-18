#!/usr/bin/env bash
# Scripted reconstruction of a RevRem run for the README hero GIF.
# This is a faithful reproduction of real `revrem` output formatting for
# demonstration — it is NOT a live model-backed capture. Rendered via VHS
# from docs/assets/revrem-demo.tape. Args are intentionally ignored.
set -euo pipefail

c_rev=$'\033[36m'   # review  -> cyan
c_rem=$'\033[33m'   # remediation -> yellow
c_chk=$'\033[32m'   # checks  -> green
c_find=$'\033[33m'  # finding -> yellow
c_ok=$'\033[1;32m'  # success -> bold green
c_dim=$'\033[2m'    # dim
c_off=$'\033[0m'

# line <time> <tag> <color> <iteration> <message> <sleep>
line() { printf '%s|%s%s%s|%-4s|%s\n' "$1" "$3" "$2" "$c_off" "$4" "$5"; sleep "$6"; }

line "12:08:23" "rev" "$c_rev" "1"   "start: codex review --base main"                              0.9
line "12:10:14" "rev" "$c_rev" "1"   "${c_find}[P1] Preserve failure artifacts when review startup fails${c_off}" 0.7
line "12:10:15" "rem" "$c_rem" "1"   "start: codex exec --full-auto --sandbox workspace-write ..."  1.1
line "12:13:41" "rem" "$c_rem" "1"   "done"                                                          0.6
line "12:13:42" "chk" "$c_chk" "1.1" "start: pytest -q"                                              0.9
line "12:14:18" "chk" "$c_chk" "1.1" "${c_ok}passed${c_off}"                                         0.6
line "12:14:19" "rev" "$c_rev" "2"   "${c_ok}clear${c_off}"                                          0.8

printf '\n%sReview-remediation loop: %sclear%s (review_clear)\n' "$c_off" "$c_ok" "$c_off"
printf '%sArtifacts: .revrem/runs/20260509T120823Z%s\n' "$c_dim" "$c_off"
printf '%sJSON summary: .revrem/runs/20260509T120823Z/summary.json%s\n' "$c_dim" "$c_off"
sleep 1.2
