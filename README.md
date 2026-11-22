<p align="center">
  <img src="docs/banner.png" alt="Seekframe - HTML and Blender scenes to MP4 for YouTube and Shorts" width="100%">
</p>

<p align="center">
  <a href="../../releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/ShadowStudioApps/seekframe?label=download&color=ff7a30"></a>
  <a href="../../releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/ShadowStudioApps/seekframe/total?color=6b5bd2"></a>
  <img alt="Windows 10/11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0b0a18">
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/github/license/ShadowStudioApps/seekframe?color=2ea043"></a>
  <a href="docs/MCP.md"><img alt="Claude MCP" src="https://img.shields.io/badge/Claude-MCP%20ready-d97757"></a>
</p>

<p align="center">
  <b>Free Windows app that turns code-made scenes into finished videos.</b><br>
  Write (or generate) a scene as one <code>.html</code> file - or build it in Blender, or let Seekframe's AI make it from
  one sentence - drop it in Seekframe, and get a clean, frame-exact MP4 with sound, for YouTube (16:9) and Shorts (9:16).<br>
  In 11 languages. <i>Seekframe was called Shadow until version 3.24.</i><br>Made by <a href="https://github.com/ShadowStudioApps"><b>Shadow Studio</b></a>.
</p>

<p align="center">
  <a href="../../releases/latest"><b>Download</b></a> &nbsp;·&nbsp;
  <a href="#quick-start">Quick start</a> &nbsp;·&nbsp;
  <a href="#features">Features</a> &nbsp;·&nbsp;
  <a href="docs/GUIDE.md">User guide</a> &nbsp;·&nbsp;
  <a href="#use-shadow-from-claude-mcp">Claude (MCP)</a> &nbsp;·&nbsp;
  <a href="CHANGELOG.md">Changelog</a>
</p>

<p align="center">
  <img src="docs/demo.gif" alt="A narrated diagram scene rendered by Seekframe" width="760">
  <br><sub>A narrated diagram scene rendered by Seekframe: voice, word captions, motion, all from one HTML file.</sub>
</p>

## Quick start

1. **Download** `Seekframe-<version>-Setup.exe` from [Releases](../../releases/latest) and run it. No admin needed.
   Windows SmartScreen may warn because the app is not code-signed: choose *More info* → *Run anyway*.
2. The setup offers to install what is missing with winget: **Google Chrome** and **ffmpeg** (both free). Without Chrome,
   Seekframe uses **Microsoft Edge**, which comes with Windows. Press **Self-test** in the app to check everything works.
3. Open Seekframe, **drop your scenes** in, press **Render**. That's it.

New versions show an **Update to vX.Y** button inside the app and install themselves.

Every button, option, output file and QC check is explained in the **[user guide](docs/GUIDE.md)**.

## Features

| Feature | What it does |
|---|---|
| **Frame-exact video** | Every frame is drawn on purpose (`seek(t)`), so the video is identical every time - no dropped frames, no screen recording. |
| **Up to 4K, 30 fps, with sound** | 1080p by default, or *1440p* / *4K* in Quality (16:9 and 9:16). The scene's own generated sound, a song or voice file next to it (*Auto*), or silent. Loudness is set to about -14 LUFS for songs and -15 LUFS for everything else, and checked *after* encoding. |
| **YouTube + Shorts in one go** | *Format Auto*: files named `short_*` or `*-short` render 9:16, the rest 16:9 - one queue, both formats. |
| **Quality check on every video** | A `.qc.txt` report: size, duration, black frames, freezes, silence, loudness and true peak. |
| **Narration with captions** | Put `<scene>.wav` + `<scene>.words.json` next to the scene: the voice is mixed in and word captions appear (2D canvas scenes). |
| **11 languages** | English, Arabic, Chinese, Hindi, Spanish, French, Portuguese, Russian, Indonesian, German, Japanese: pick one at the top (Auto follows Windows). |
| **Smart Seekframe (AI)** | *New video (AI)* turns an idea into a narrated, captioned scene (Claude writes it, Kokoro speaks it, Seekframe checks every frame); *AI...* fixes a broken scene (you approve the change) or writes the YouTube title, description and tags from the video. Uses your Claude subscription through Claude Code, nothing paid per use. |
| **Video + song** | Drop a finished video with its song next to it (`dance.mp4` + `dance.mp3`): Seekframe measures the video's motion, cuts and loop point and the song's beats and chorus, then gives a short clip the chorus (its strongest moment on the beat), loops a short 16:9 clip to the song, or cuts a long one; -14 LUFS, Music folder, QC. |
| **Blender scenes** | `.blend` files render through your installed Blender (Eevee, Cycles on the GPU, or Workbench) with the same sound, Shorts and QC. [Guide](docs/BLENDER.md) |
| **Check before you render** | *Check frames* shows a contact sheet in both formats in seconds and lists page errors and frames that are not repeatable. Before a render Seekframe also tells you when a scene misses `window.__ready`, `seek(t)`, `DURATION` or its canvas, instead of failing later. |
| **Batch-friendly** | *Add folder...* (or drop a folder), *Skip scenes already rendered*, a time estimate per scene and for the whole queue, and a Windows notification when it is done. |
| **Subtitles** | A narrated video gets a `.srt` subtitle file next to it, ready to upload to YouTube. |
| **Upload to YouTube** | *YouTube...* uploads the finished videos to your channel with the title, description, tags and *Made for Kids* from `metadata.txt` (Private by default), through your own free Google Cloud project. `metadata.txt` can also set the AI-content label (`AI: yes`), the thumbnail and a publish time (`PUBLISH:`); Seekframe asks before uploading a video without one. [Guide](docs/YOUTUBE.md) |
| **Tidy output folders** | *Folder Auto* puts songs in `Music\` and everything else in `Video\`; a Short is saved next to its video. |
| **Fast** | Several copies of the scene draw frames at the same time: about 4x faster than one at a time (measured: 20 s of 1080p in 13 s, of 4K in 44 s, RTX 5070 Ti). *Capture*: Best quality (PNG, default) or Fast (JPEG, about 1.2x faster, very slightly softer). |
| **Projects** | *Project > Save project* keeps the list of scenes, each row's narration and all options in a `.shadow` file; open it (or drop it on Seekframe) to get it all back. |
| **Self-test** | One button renders a 2-second test video with sound and checks it, and says which step failed and what to install. |
| **Claude can run it** | A local MCP server lets Claude render, follow progress, preview frames, read QC reports and upload to YouTube (it shows you a preview first and uploads only after your yes). Works with other MCP clients too (Gemini CLI, Cursor, VS Code, ...). [Guide](docs/MCP.md) |
| **Assistant panel** | Ask in plain words inside the app ("render this folder and check the quality") and watch Claude do it. Runs on your Claude subscription through Claude Code, no API key. [Guide](docs/ASSISTANT.md) |
| **Safe and tidy** | Each scene gets its own output folder; nothing is ever overwritten (`_2`, `_3`); failed renders leave a log. |
| **Free and offline** | No Seekframe account, no paid services. Rendering runs on your PC; nothing leaves it unless you press *Upload* (to your own YouTube channel) or one of the AI buttons (through your own Claude Code - see the [privacy policy](docs/PRIVACY.md)). Only your scenes' own CDN links (e.g. three.js) need the internet. |

<p align="center">
  <img src="docs/screenshot.png" alt="Seekframe 3.28, dark theme: the sidebar (Queue, New video, AI tools, YouTube, Project, Assistant, Settings, About) and a song video and its Short in the queue" width="49%">
  <img src="docs/screenshot_light.png" alt="Seekframe 3.28, light theme" width="49%">
</p>

<p align="center">
  <img src="docs/screenshot_ai_new.png" alt="New video (AI): an idea, a style and a length; Claude writes the narration and the scene, Kokoro makes the English voice" width="49%">
  <img src="docs/screenshot_ai_fix.png" alt="AI... Fix the scene: the problems Seekframe found plus your own words; Claude fixes a copy, Seekframe checks it, you press Apply" width="49%">
  <br><sub><b>New video (AI)</b> makes a narrated, captioned scene from one idea; <b>AI...</b> fixes a scene or writes its YouTube text - <a href="docs/GUIDE.md#smart-shadow-ai">how it works</a>.</sub>
</p>

<p align="center">
  <img src="docs/screenshot_arabic.png" alt="Seekframe in Arabic: every button, option and status translated" width="62%">
  <br><sub>The same window in Arabic - one of 11 languages (the list at the top; Auto follows Windows).</sub>
</p>

<p align="center">
  <img src="docs/screenshot_youtube.png" alt="Upload to YouTube: the video and its Short with titles from metadata.txt, the Publish column and the AI label, thumbnail and schedule options" width="62%">
  <br><sub><b>YouTube...</b> uploads the video and its Short with the title, description and tags from <code>metadata.txt</code> - <a href="docs/YOUTUBE.md">how to set it up</a>.</sub>
</p>

## How it works

```mermaid
flowchart LR
  A["scene.html<br>or scene.blend"] --> B["Seekframe"]
  S["song / voice<br>(optional)"] --> B
  B --> C["Chrome (headless)<br>or Blender<br>draws frame t"]
  C --> D["ffmpeg<br>x264 + AAC"]
  D --> E["video.mp4<br>+ video_shorts.mp4"]
  E --> F["quality check<br>.qc.txt"]
```

Seekframe opens each scene in your installed Chrome or Edge (or Blender), lets several copies of it draw different frames at
the same time, and pipes the frames, in order, straight into ffmpeg while the sound is rendered and loudness-matched. Nothing depends on how fast your PC is: a slow machine just
takes longer and produces the same video.

## Make a scene

A scene is one HTML file that provides:

- `<canvas id="c">`; with `?render=1` in the URL it must not autoplay
- `window.__ready = true` once loaded, and `window.DURATION` (seconds)
- `window.seek(t)` draws exactly the frame at time `t` (a pure function of `t`: no real-time loop, no `Math.random` inside `seek` - use a seeded random). Seekframe gives every render page the same seeded `Math.random` and a frozen `Date`, so random choices made while loading match in every copy
- the size from the `w` and `h` URL parameters (read `h` to support 9:16)
- optional: `window.STYLE_SOUND(k)` + the `SOUND.renderOffline` kit for generated sound, `window.THUMBNAIL_T` for an automatic thumbnail

[`tests/fixtures/webgl_min.html`](tests/fixtures/webgl_min.html) is a minimal working scene. Before a long render, press
**Check frames** (or run `python tools/check_frames.py scene.html`): a contact sheet in both formats in a few seconds, and a check that `seek(t)` is pure.

**Command line:** `Seekframe.exe --render scene.html out.mp4 [--vertical] [--preset draft|good|best|1440p|4k] [--silent] [--fast]`,
`Seekframe.exe --check scene.html [--only 16:9|9:16]` (contact sheet `<scene>.check.jpg` next to the scene),
`Seekframe.exe --selftest` (renders a test video and checks it), `Seekframe.exe project.shadow` (opens a project)

## Use Seekframe from Claude (MCP)

Claude (Claude Code, Claude Desktop or any MCP client) can render with Seekframe for you - a scene or a whole folder - follow
the progress, cancel, preview frames, read the quality report and upload the result to YouTube (preview first, then only
after your yes), without opening the window. It is local and free
(no API keys, nothing leaves your PC). It runs from a copy of this repository with Python, not from the installed exe:

```
git clone https://github.com/ShadowStudioApps/seekframe C:\Seekframe
python -m pip install "mcp>=2" playwright pillow tkinterdnd2 sv-ttk darkdetect numpy
claude mcp add shadow --scope user -- python C:\Seekframe\tools\mcp_server.py
```

Then copy `claude-skills\shadow-mcp` to `%USERPROFILE%\.claude\skills\` so Claude knows when to use it, and check with
`claude mcp list` (`shadow: ... Connected`). Full guide, the tool list and setups for Claude Desktop, Cursor, VS Code,
Windsurf and Gemini CLI (plus an optional localhost-only HTTP mode): [docs/MCP.md](docs/MCP.md).

**Assistant panel:** the **Assistant** button in the window opens a chat with Claude that uses these tools. It runs on your
Claude subscription through the installed Claude Code CLI (no API key). Claude may only read files and use Seekframe's tools;
stopping a render or uploading to YouTube needs your click. Details and the exact permissions: [docs/ASSISTANT.md](docs/ASSISTANT.md).

## FAQ

**Windows warns "Windows protected your PC".** The installer is not code-signed (a certificate costs money). Choose
*More info* → *Run anyway*. The file on the release page has its SHA-256 listed, so you can check it was not changed.

**The top bar shows "ffmpeg (missing)" right after installing.** Sign out and in once (or restart) so Windows refreshes
the PATH, then press *Re-check*.

**I don't have Google Chrome.** Seekframe uses Microsoft Edge instead (same engine, part of Windows); the top bar then says
*Edge (Chrome not found)*.

**Does it need a graphics card?** No. Scenes render on any PC; a GPU just makes three.js and Blender scenes faster.

**My 9:16 video looks like a squeezed 16:9.** The scene must read the `h` URL parameter and lay itself out for a tall
frame. Seekframe warns before rendering a 9:16 version of a scene that does not.

**Where are my settings and logs?** Settings: `%USERPROFILE%\.shadow_renderer.json`. Log: `%USERPROFILE%\shadow.log`
(or press *Open log*). A failed render also leaves a `.log` in its output folder.

Something else? [Open an issue](../../issues/new/choose).

## Build from source

Python 3.12 on Windows: `run.bat` runs it from source, `build_exe.bat` builds `dist\Seekframe.exe` (PyInstaller),
`build_installer.bat` builds the setup ([Inno Setup 6](https://jrsoftware.org/isinfo.php), free).
Tests: `python tests\regression.py`, `tests\test_queue_gui.py`, `tests\test_updater.py`, ... (`tests\smoke_test.py` runs on Linux).
Release (maintainer): double-click `publish_update.bat` (asks the new version and notes, runs the tests, builds, uploads, releases).

## License

[MIT](LICENSE) · [Privacy policy](docs/PRIVACY.md). Seekframe uses Google Chrome or Microsoft Edge (via Playwright), ffmpeg and, for `.blend` files, Blender - all installed
separately under their own licenses. Videos you make with Seekframe are yours.
