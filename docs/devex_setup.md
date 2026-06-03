# Antigravity CLI Custom Status Line Setup

This document details the configuration and implementation of a premium, dynamic status line for the new **Antigravity CLI** (`agy`).

## Overview

Whenever the agent state changes, the Antigravity CLI pipes a metadata JSON payload to a configured external command via `stdin`, which then prints the formatted string to `stdout` to render in the CLI terminal window's bottom status line.

By configuring a custom Python script, we parse this metadata and query Git dynamically to build a beautiful, color-coded, and responsive status indicator.

---

## Configuration Details

### 1. The Script: `statusline.py`
The custom status line script is located at:
[statusline.py](file:///home/cmf/.gemini/antigravity-cli/statusline.py)

This script:
1. Reads the JSON payload piped to `stdin`.
2. Extracts workspace dir, active model display name (preserving effort levels like `(Medium)`), context usage, plan tier, and agent state.
3. Automatically runs `git rev-parse` in the current working directory to retrieve the active branch name.
4. Identifies the local Antigravity server process dynamically by parsing `/proc` and matching socket inodes with `/proc/net/tcp` to find its listening ports.
5. Performs a Connect-RPC POST request to the local server's `GetUserStatus` endpoint to fetch the active model's remaining quota fraction and reset time.
6. Renders the status line in a clean, professional, emoji-free textual format using ANSI escape codes for styling (without prefixes for workspace, branch, model, and state; abbreviating context to `ctx:`).
7. Parses and converts the UTC reset time to the user's local timezone.
8. **Dynamically drops segments** (starting with state, then model name, then git branch name) to preserve quota and context information for as long as possible if the combined text length exceeds the terminal width (`terminal_width`).

### 2. The Configuration: `settings.json`
The CLI settings are located at:
[settings.json](file:///home/cmf/.gemini/antigravity-cli/settings.json)

The `statusLine` configuration block was updated to point to the python script:
```json
  "statusLine": {
    "type": "command",
    "command": "/home/cmf/.gemini/antigravity-cli/statusline.py",
    "enabled": true
  }
```

---

## JSON Payload Reference

For reference, the JSON payload piped by `agy` to `stdin` has the following schema:

```json
{
  "cwd": "/home/cmf/code/code-review-loop",
  "session_id": "f71bd94b-bc14-4bb5-9095-642766556feb",
  "conversation_id": "f71bd94b-bc14-4bb5-9095-642766556feb",
  "transcript_path": "/home/cmf/.gemini/antigravity/brain/f71bd94b-bc14-4bb5-9095-642766556feb/.system_generated/logs/transcript.jsonl",
  "model": {
    "id": "Gemini 3.5 Flash (Medium)",
    "display_name": "Gemini 3.5 Flash (Medium)"
  },
  "workspace": {
    "current_dir": "/home/cmf/code/code-review-loop",
    "project_dir": "file:///home/cmf/code/code-review-loop"
  },
  "version": "1.0.4",
  "context_window": {
    "total_input_tokens": 24067,
    "total_output_tokens": 650,
    "context_window_size": 1048576,
    "used_percentage": 2.295,
    "remaining_percentage": 97.705,
    "current_usage": {
      "input_tokens": 17427,
      "output_tokens": 220,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 0
    }
  },
  "exceeds_200k_tokens": false,
  "product": "antigravity",
  "agent_state": "working",
  "vcs": {
    "type": "git"
  },
  "sandbox": {
    "enabled": false
  },
  "plan_tier": "Google AI Pro",
  "email": "colinfarmer.gg1@gmail.com",
  "terminal_width": 80
}
```

---

## Modifying the Status Line Style

You can customize the theme colors and symbols by editing the [statusline.py](file:///home/cmf/.gemini/antigravity-cli/scratch/statusline.py) file. 

* **To change colors:** Modify the ANSI color codes in the variables under the `Colors` section of the script.
* **To change icons:** Replace or remove the emoji/Unicode characters (`📁`, `⎇`, `🤖`, `⚡`, `💎`, `●`) in the segment string formatting.
