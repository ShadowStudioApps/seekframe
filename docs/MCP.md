# Seekframe MCP server

`tools/mcp_server.py` lets Claude (Claude Code, Claude Desktop, any MCP client) use Seekframe directly: render scenes or whole
folders, follow progress, cancel, run check_frames, read QC reports, list outputs. Local and free: stdio transport (an optional
HTTP mode listens on 127.0.0.1 only), no API keys. Works with Claude and other MCP clients (see *Other AI clients*). It does not need the Seekframe window open. It renders with the GUI queue's own function (`app.render_scene`, which
`App._run_one` also calls), so the output files, folders, QC reports and warnings are the same as the GUI's.

Requirements: a copy of this repository (the source, not only the installed Seekframe.exe - the server does not run inside
the exe), Python 3.12 with `mcp` (2.x), `playwright`, `Pillow` (for check_frames), plus Google Chrome and ffmpeg on PATH,
the same as running Seekframe from source. Below, `C:\Seekframe` stands for the folder you cloned it into - use your own path.

## Set it up (once)
```
git clone https://github.com/ShadowStudioApps/seekframe C:\Seekframe
python -m pip install "mcp>=2" playwright pillow tkinterdnd2 sv-ttk darkdetect numpy
```
Chrome: install Google Chrome normally (Seekframe renders with the installed Chrome). ffmpeg: `winget install -e --id Gyan.FFmpeg`
(open a new terminal afterwards so it is on PATH).
Optional, so Claude knows when and how to use the tools: copy `claude-skills\shadow-mcp` to `%USERPROFILE%\.claude\skills\shadow-mcp`.

## Connect it to Claude Code
Every session, every folder (user scope):
```
claude mcp add shadow --scope user -- python C:\Seekframe\tools\mcp_server.py
```
Only inside this repo (project scope; writes `.mcp.json` into the repo, the same command with `--scope project`).
Check: `claude mcp list` should show `shadow: ... - Connected`. In a session, `/mcp` lists the 9 tools.
Remove: `claude mcp remove shadow --scope user`.

**Easiest (3.32):** Seekframe > Settings > *AI connections*: tick the app (Claude Code, Claude Desktop, Cursor, VS Code,
Windsurf / Devin, Gemini CLI, ChatGPT / Codex, Grok Build) and Seekframe writes the entry below into that app's settings for you (only its own
`shadow` entry; the old file is kept as `<file>.seekframe-backup`). The Microsoft Store build of Claude Desktop keeps its
file in `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\`. ChatGPT desktop / Codex: `%USERPROFILE%\.codex\config.toml` (one file for both); Grok Build: `%USERPROFILE%\.grok\config.toml` (same `[mcp_servers.shadow]` table),
table `[mcp_servers.shadow]` with `command` and `args`.

Claude Desktop, Cursor, VS Code, Windsurf, Gemini CLI by hand: see *Other AI clients* below. Inside the Seekframe window there is
also an **Assistant** panel that chats with Claude Code and these tools: see [ASSISTANT.md](ASSISTANT.md).

The skill in `claude-skills/shadow-mcp/SKILL.md` (copied to `~/.claude/skills/shadow-mcp/`) tells Claude when and how to use the tools.

## Other AI clients
The server speaks the open MCP standard, so any MCP client can use it. All of them start the same command,
`python C:\Seekframe\tools\mcp_server.py` (stdio). In JSON, write every `\` as `\\`. Each client keeps its own config file;
the snippets below go into it. The paths and key names come from each client's official docs (read 2026-11-19).
**Tested** means that the client itself connected to the Seekframe server on this PC.

| Client | Status |
|--------|--------|
| Claude Code | tested (`claude mcp list` → Connected; tools used in real sessions and by the Assistant panel) |
| Gemini CLI 0.68 | tested: `gemini mcp list` → `✓ shadow ... (stdio) - Connected`, and over the HTTP mode below `(http) - Connected` |
| Claude Desktop | not tested in the app (config format from the official MCP docs) |
| Cursor | not tested (not installed here) |
| VS Code (GitHub Copilot agent mode) | not tested (not installed here) |
| Windsurf | not tested (not installed here; its docs now redirect to Devin Desktop) |
| ChatGPT | not possible locally (see below) |

**Claude Desktop**: `%APPDATA%\Claude\claude_desktop_config.json`. Restart Claude Desktop fully afterwards. The server
appears under *Connectors*. Logs: `%APPDATA%\Claude\logs\mcp-server-shadow.log`.
```json
{ "mcpServers": { "shadow": { "command": "python", "args": ["C:\\Seekframe\\tools\\mcp_server.py"] } } }
```

**Cursor**: global `%USERPROFILE%\.cursor\mcp.json` (or `.cursor\mcp.json` in a project). Check it under Output → *MCP Logs*.
```json
{ "mcpServers": { "shadow": { "type": "stdio", "command": "python", "args": ["C:\\Seekframe\\tools\\mcp_server.py"] } } }
```

**VS Code, GitHub Copilot agent mode**: VS Code's current format is `%USERPROFILE%\.copilot\mcp-config.json`. The older
`.vscode\mcp.json` with the top key `"servers"` still works, but VS Code says that format will be removed in February 2027.
Check it with *MCP: List Servers* (Command Palette), and use Copilot Chat in **Agent** mode.
```json
{ "mcpServers": { "shadow": { "type": "stdio", "command": "python", "args": ["C:\\Seekframe\\tools\\mcp_server.py"], "tools": ["*"] } } }
```

**Windsurf**: Windsurf's MCP docs now redirect to *Devin Desktop*. Its user config is `%APPDATA%\devin\mcp_config.json`;
older Windsurf builds used `%USERPROFILE%\.codeium\windsurf\mcp_config.json` (not checked). Check it under
*Customize → MCPs*.
```json
{ "mcpServers": { "shadow": { "command": "python", "args": ["C:\\Seekframe\\tools\\mcp_server.py"] } } }
```

**Gemini CLI**: `%USERPROFILE%\.gemini\settings.json` (or `.gemini\settings.json` in a project). Check it with
`gemini mcp list`, or with `/mcp` inside a session. Gemini CLI disables every MCP server in a folder it does not trust,
so run `gemini trust` in your working folder first (measured: before that, `shadow` showed as *Disabled*).
```json
{ "mcpServers": { "shadow": { "command": "python", "args": ["C:\\Seekframe\\tools\\mcp_server.py"] } } }
```

**ChatGPT**: ChatGPT only connects to *remote* MCP servers: a URL that OpenAI's servers can reach over the internet
(developer mode: *Add custom MCP server*, using SSE or streaming HTTP). It cannot start a local program, and it cannot
reach `localhost` on your PC. To use Seekframe from ChatGPT you would have to publish the HTTP mode on the internet
(a tunnel). Then anyone with the URL could render and read files through Seekframe on your PC. Seekframe does not support
that and this guide does not cover it.

## Optional local HTTP mode
Some clients prefer a URL to a command. The server can also speak MCP over streamable HTTP. This mode is **off by
default**: it runs only when you start it yourself, and it listens on `127.0.0.1` only. Other PCs and the internet cannot
reach it. Requests whose `Host` is not `127.0.0.1` / `localhost` are refused (protection against DNS rebinding from web
pages).
```powershell
python C:\Seekframe\tools\mcp_server.py --http --port 8765
```
The URL is `http://127.0.0.1:8765/mcp`. Keep that terminal open while the client uses it, and press Ctrl+C to stop.
- Gemini CLI (tested): `{ "mcpServers": { "shadow": { "httpUrl": "http://127.0.0.1:8765/mcp" } } }`
- Cursor (not tested): `{ "mcpServers": { "shadow": { "url": "http://127.0.0.1:8765/mcp" } } }`
- VS Code (not tested): `{ "mcpServers": { "shadow": { "type": "http", "url": "http://127.0.0.1:8765/mcp", "tools": ["*"] } } }`

With stdio, a render lives as long as the client keeps the server running. In HTTP mode it lives as long as that terminal
stays open, so jobs survive a client restart.

## Tools
| Tool | What |
|------|------|
| `shadow_info` | version, Chrome / ffmpeg / playwright found, default Save to, settings choices, last job |
| `shadow_plan(paths, ...)` | dry run: each scene's Format, Audio, narration mark, output path, skipped outdated 9:16 / up-to-date scenes, estimated time (`estimate_s`), warnings |
| `shadow_render(paths, out_dir, quality, format, sound, audio_file, capture, narration, outdated, recursive, skip_up_to_date)` | starts a job, returns `job_id` at once; `skip_up_to_date=true` keeps scenes whose mp4 is newer than the scene and its audio (default off); a narrated scene also gets `<video>.srt` |
| `shadow_progress(job_id, wait_seconds)` | state, percent, each scene's status text (`Frames 120/900`, `Done · QC OK`), ETA per scene and for the whole job (`eta_s`, `eta`: "about 12 min · done ~15:40"), outputs, QC, warnings; `wait_seconds` (max 55) blocks until the job ends |
| `shadow_cancel(job_id, current_only)` | Stop queue / Cancel current |
| `shadow_jobs` | jobs of this server session |
| `shadow_check_frames(scene, only, times, show_sheet)` | `tools/check_frames.py`: contact sheet (returned as an image), page errors, seek(t) purity |
| `shadow_qc(path, rerun, quality)` | read `.qc.txt` for an mp4 / folder; `rerun` checks the mp4 again |
| `shadow_outputs(path or job_id)` | videos (size, duration, audio, QC status), QC reports, logs, thumbnails |
| `shadow_video_look(video, song)` | 3.18: a finished video + its song (`<video>.mp3` next to it by default): contact sheet (as an image), motion every 0.5 s, cuts, loop point, the song's BPM / chorus and the automatic plan |
| `shadow_video_song(video, song, mode, song_start, loop_end, out_dir, folder)` | renders it like the queue (Music folder, QC, thumbnail); `mode auto|chorus|loop|trim|as_is`, `-1` = the plan's value; follow with `shadow_video_song_progress(job_id, wait_seconds=50)` |
| `shadow_youtube` | signed-in YouTube channels, whether the OAuth client file is there (setup: [YOUTUBE.md](YOUTUBE.md)) |
| `shadow_upload_preview(video, channel, privacy, ai, thumbnail, publish, meta, scene)` | what an upload WOULD send (title, description, tags, privacy, AI label, publish time UTC, thumbnail, notes); sends nothing |
| `shadow_upload(same arguments)` | uploads in the background, returns `upload_id`. Only after the owner approved the preview. Private by default |
| `shadow_upload_progress(upload_id, wait_seconds)` | percent; when done the video link, Studio link, privacy, scheduled time, thumbnail result |
| `shadow_upload_cancel(upload_id)` | stops after the current 8 MB chunk; nothing is published |

Blender `.blend` scenes work in every tool (paths may mix .html and .blend); `shadow_render` / `shadow_plan` also take
`engine` (`scene|eevee|cycles|workbench`) and `device` (`auto|gpu|cpu`), `shadow_check_frames` takes `engine`. See docs/BLENDER.md.

Settings use the GUI's choices: quality `best|good|draft|1440p|4k`, format `auto|16:9|9:16`, sound `auto|generated|none|file`,
capture `png|jpeg`, narration `auto|off`, outdated `skip|render` (the GUI asks in a dialog; the server cannot, default skip).
Defaults: best, auto, auto, png, auto, skip; out_dir = the GUI's Save to.

Upload choices: `privacy` `private|unlisted|public` (default private); `ai` `auto|yes|no` (auto = `AI:` in metadata.txt);
`thumbnail` `auto|none|<image>` (auto = `THUMBNAIL:` or `<video>_thumb.jpg`); `publish` `auto|none|<date and time>`
(auto = `PUBLISH:`; e.g. `2026-11-25 05:00 Sydney`). metadata.txt is read next to the video, or `meta`, or next to `scene`.
The channel is signed in once by the owner in the Seekframe window (YouTube... -> Sign in...): the server never sees a password.

## Notes
- Jobs run one at a time on one background thread; a second job waits. Jobs live as long as the server process (the client
  restarts it per session); the files stay.
- MCP clients start the server with a cut-down environment (no `PROGRAMFILES`). The server puts back the standard Windows
  folders, otherwise Chrome is not found (measured: `Missing: chrome`).
- Logs go to `~/shadow.log` (`SHADOW_LOG` env overrides it, used by the tests). Nothing is printed to stdout (the MCP channel).
- Test: `python tests/test_mcp_server.py` (fixtures only; includes a real stdio session, the HTTP mode (M7) and, if Chrome
  is installed, a real draft render).
