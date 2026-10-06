# Current Codex models

Merge `.revrem.toml` into the target repository's configuration, or into
`~/.config/revrem/profiles.toml` to make the profile available across repositories.
Do not overwrite existing profiles. Add the repository's own tests:

```sh
revrem doctor --profile current-codex --base main --check 'pytest -q'
revrem --profile current-codex --base main --check 'pytest -q' --dry-run
revrem --profile current-codex --base main --check 'pytest -q'
```

This profile uses GPT-6 Astra for review, GPT-6 Luna for triage, and GPT-6.1
Sol for remediation. It caps iterations, wall time and individual model calls.
Automatic commits are off unless explicitly enabled elsewhere. The default
whitespace check is not a substitute for project tests.

Codex CLI 0.160.1 completed live calls with these three IDs on 2026-10-06.
`gpt-6.1-luna` was rejected by the tested ChatGPT account; the documented Luna ID
is `gpt-6-luna`. Account access can change. See the
[official model guide](https://developers.openai.com/api/docs/guides/latest-model).
