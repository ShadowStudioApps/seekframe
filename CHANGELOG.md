# Changelog

Every release is on the [Releases](../../releases) page with its `Seekframe-<version>-Setup.exe`. Installed copies update
themselves: Seekframe shows **Update to vX.Y** when a new release is out.

## 3.33
- **Cloud accounts without their apps** (Settings > *Cloud accounts*): sign in to Google Drive, OneDrive, Dropbox, Box or
  pCloud in your browser (Seekframe never sees the password). Uses rclone (free, open source); *Get rclone* downloads the
  official release and checks it. The sign-ins are kept encrypted for your Windows account only.
- **Queue > Cloud...**: browse a signed-in account and add scenes, videos or whole folders. A scene brings its whole folder
  (song, voice, pictures) into `Videos\Seekframe cloud\<account>\...`; at the top of an account only the file you picked.
- **Also upload finished videos to** an account: each finished video (and its subtitles / thumbnail) goes to
  `Seekframe/<same folders as on your PC>` there, in the background, while the next render runs.
- **Cloud...** sits in the sidebar; the **Settings page scrolls** and the window is never taller than the screen.

## 3.32
- **Settings > AI connections** (was *Claude connection*): every AI app found on your PC (Claude Code, Claude Desktop,
  Cursor, VS Code Copilot, Windsurf / Devin, Gemini CLI, Codex) has a tick box. Tick it and Seekframe sets itself up in
  that app's own settings (only its own `shadow` entry; the old file is kept as `<file>.seekframe-backup`). A green light
  shows the connected ones, *In use now* the ones running Seekframe, and Windows shows a notification when an app
  connects or starts using Seekframe. Apps that are not installed are listed in one line instead.
- **Choose the AI for Seekframe's own AI buttons**: Claude Code (default) or Gemini CLI. *Fix the scene*, *YouTube text*
  and *New video* use the one you pick (checked first, with a notification). Gemini may only read files and edit the one
  file the job names (a Gemini policy file: shell, web, helper agents and MCP are refused). The Assistant chat stays on
  Claude Code.

## 3.31
- **Update notice**: when a new version is out, a bar appears under the page title (*Update now*, *What's new*, *Later*) and
  Windows shows one notification for that version. *Check for updates* left the sidebar; it is on the About page.
- **Settings > Save videos to** has more places: *This PC* (your Videos folder), OneDrive, Google Drive, Dropbox, iCloud Drive,
  Box and *Network drive (NAS)...*. A cloud app Seekframe cannot find, and the NAS button, ask you for the folder.
- **Smoother Assistant**: opening or closing the Assistant no longer resizes the whole window (the table was squeezed while
  it moved); the window only grows when it is too narrow for both.
- **Shadow Studio** mark (logo + name) at the bottom of the sidebar; a click opens the studio's page.

## 3.30
- **The render options are back on the Queue page**: Quality, Format, Sound, Capture and Blender sit right under the table.
  *Save to* and *Folder* are in Settings.
- **Settings > Save videos to**: buttons for the cloud folders found on your PC (OneDrive, Google Drive, Dropbox, iCloud), a
  note for a NAS (`\NAS\Videos` or a mapped drive) and **Check access**, which tests that Seekframe can write there and
  shows the free space.
- **Settings > Claude connection (MCP)**: green lights when Claude Code is installed, Seekframe is set up for it, and an MCP
  connection is open right now (with how many).
- **Settings > AI account**: the AI features use your Claude subscription by default. Anyone without one can choose **their
  own Anthropic API key** instead (Seekframe asks first, because every request is then billed by Anthropic). The key is
  stored encrypted by Windows for your account only, is never shown again in full, and is used only in that mode.

## 3.29
- **Smoother page switching**: the Queue / Settings / About pages are built once and only brought to the front, instead
  of being rebuilt on every click (measured in 3.29: 117 ms -> about 65 ms per switch on average; with the options back on the Queue page in 3.30 it is about 95 ms).

## 3.28
- **A calmer window with a sidebar**: Queue, New video, AI tools, YouTube, Project and Assistant on the left; the
  render options, the setup check and the language moved to their own **Settings** page, so the Queue page shows just
  your scenes (with a one-line summary of the options that opens Settings). The ☰ button hides or shows the sidebar,
  and Seekframe remembers your choice.
- **About** page: version, Shadow Studio, and links to the GitHub page, the user guide, what's new, the privacy policy
  and "Report a problem".
- The top bar shows just the page name (the "HTML scene → MP4" line is gone).

## 3.27
- **Silent installs finish on their own**: `Seekframe-X.Y-Setup.exe /SILENT` (and installs through winget) no longer
  try to install Chrome / ffmpeg in a console window that waits for an answer. A normal (double-click) install still offers
  them. Through winget, ffmpeg comes as a dependency.

## 3.26
- Seekframe now lives at **github.com/ShadowStudioApps/seekframe**, the home of **Shadow Studio** (the studio that makes
  Seekframe and the apps that come after it). Old links and the update check are redirected, so nothing changes for you.
- The installer and Apps & features show Shadow Studio as the publisher.

## 3.25
- **Shadow is now called Seekframe.** The name Shadow was already used by other Windows apps (Shadow PC, and a "Shadow
  Studio" in the Microsoft Store), so the app got a name of its own, after how it works: `seek(t)` draws exactly the frame
  at time t. The program is now `Seekframe.exe`, the setup `Seekframe-X.Y-Setup.exe`, and the GitHub page
  github.com/ShadowStudioApps/seekframe (the old address still leads there).
- Nothing else changes: your settings, projects (`.shadow` files), scenes, output folders, the YouTube sign-in and the
  Claude connection (MCP server `shadow`) all work as before. Updating from Shadow installs Seekframe in the same folder
  and replaces the old shortcuts.

## 3.24
- New README pictures (New video (AI), the AI window, Shadow in Arabic) and an updated banner; the privacy policy now
  lists what the AI buttons send (to Anthropic, through your own Claude Code).
- The AI windows use the app's own font instead of a typewriter font, and new rows say *Queued* in your language.

## 3.23
- The release that carries the 3.22 fix below (no other change).

## 3.22
- **Fix: changing the language crashed the restarted Shadow** ("Failed to execute script pyi_rth_pkgres", then "Failed to
  remove temporary directory"). The new Shadow was started inside the closing one's temporary folder, which Windows was
  deleting at that moment. It now starts as its own, independent copy (the same fix the updater already had).

## 3.21
- The first release with everything in 3.18, 3.19 and 3.20 below: video + song, Smart Shadow (New video (AI), AI...) and
  the 11 languages.

## 3.20
- **Shadow in your language**: English, العربية, 中文, हिन्दी, Español, Français, Português, Русский, Bahasa Indonesia,
  Deutsch and 日本語. Pick it from the list at the top (Auto = your Windows language); Shadow restarts in it. Buttons,
  options, messages, the Status column and the windows are translated. Your settings and projects stay the same in every
  language, so switching back and forth changes nothing else.
- Arabic, Hindi, Chinese and Japanese use a Windows font that has their letters, so the text is sharp instead of small
  and blurry.
- Smart Shadow answers in the app's language when you don't write a note of your own.

## 3.19
- **Smart Shadow - Claude inside the app** (through your Claude subscription and the installed Claude Code, like the
  Assistant: no API key, nothing paid per use). Claude can only read files and change the one file each job is about.
- **New video (AI)...** (top bar): write an idea, pick a style and a length. Claude writes the narration, Shadow makes an
  English voice with Kokoro (free, on your PC) and the word timings, Claude builds the scene to match the words, and Shadow
  checks every frame and sends anything wrong back to Claude. The finished scene lands in the queue with its voice and word
  captions attached: look at it, then Render. Without Kokoro installed the video gets music instead of a voice.
- **AI...** (under the table), for the selected row:
  - **Fix the scene**: starts from what went wrong (a failed render and its log, the quality check, Check frames) plus
    anything you type. Claude fixes a copy, Shadow checks the copy again, and you see the changes. Nothing changes until you
    press **Apply** (the original is kept in `.shadow_backup` next to it). *Check frames* now offers **Fix with AI...** too.
  - **Write YouTube text**: Claude looks at the rendered video and writes `metadata.txt` (title, description, tags,
    audience, AI label, Short section) that *YouTube...* uploads with. An existing one is never overwritten without asking.

## 3.18
- **Video + song**: drop a finished video (.mp4, .mov, .webm...) into Shadow with its song next to it (same name, e.g.
  `dance.mp4` + `dance.mp3`) or choose the song with Sound = *External file*. Shadow looks at the video itself (motion,
  cuts, the strongest moment, where it can loop) and at the song (beats, chorus) and joins them:
  a 9:16 or short clip gets the song's chorus, placed so the video's strongest moment lands on it; a short 16:9 clip loops
  to the song's length with a soft seam; a longer video is cut to the song. The song is loudness-matched like every song
  render (-14 LUFS), the video keeps its own size, and it goes to the *Music* folder with a QC report and a thumbnail.
  *Check frames* on a video shows a contact sheet and the plan before rendering.
- From Claude (MCP): `shadow_video_look` shows Claude the video's frames and numbers, so Claude can decide where the song
  starts or where the video loops, then `shadow_video_song` renders it.
- Waddle Club tool: `assemble.py --sync lyrics` cuts the shots on the lyrics (each line gets the shot that shows it, real
  freezes on "freeze" lines).

## 3.17
- **Correct colours on YouTube**: videos are now converted and tagged as BT.709 (what YouTube and players use for HD).
  Before, the colours were converted the older BT.601 way and left untagged, so reds and greens shifted slightly once
  uploaded (measured: pure red was stored as luma 81 instead of 63). No speed cost (measured at 1080p: PNG 22.2 -> 21.8,
  JPEG 18.4 -> 18.2 ms per frame).
- **Opening a project no longer asks for a song file**: a project saved with Sound = *External file...* popped up the
  file picker when opened, although it already names its song. Choosing External file by hand still asks.
- **Random layouts stay the same in every copy**: since 3.15 several copies of a scene draw frames at once. A scene that
  uses `Math.random()` or `Date.now()` while loading now gets the same values in every copy (and in every render), so the
  video cannot flicker between copies. Check frames shows the same.
- **Capture label fixed**: *Fast (JPEG)* now says *~1.2x faster* (measured after 3.15 made PNG fast too; it said ~2x). A
  Fast choice saved in your settings or in a project is kept.
- Docs: README, user guide and the Claude skill describe everything from 3.13-3.16 (4K, faster renders, projects, Edge,
  Self-test, AI label / thumbnail / schedule, uploads from Claude); new screenshots.

## 3.16
- Inside only: app.py (2,170 lines) is split into smaller files (`scene_paths.py`, `projects.py`, `shadow_util.py`,
  `dialogs.py`); Shadow works exactly as before. The tests no longer write to your own shadow.log.
- **Assistant fix**: when Claude Code crashed in the Assistant panel, the error was sometimes not shown (the panel took
  the crash for a process it had stopped itself). It is always shown now.

## 3.15
- **About 4x faster renders**: Shadow now draws the frames in several copies of the scene at once and takes each picture
  straight from the browser, instead of one frame at a time. Measured on a real Moon Shift scene (20 s, PNG, with ffmpeg):
  1080p 53 s -> 13 s, 1440p 88 s -> 22 s, 4K 185 s -> 44 s. Same file size and quality; a scene that keeps a little state
  between frames can differ by an invisible amount (measured PSNR 46 dB or more). `SHADOW_CAPTURE_WORKERS=1` gives frames
  identical to before (still about 1.6x faster).
- **YouTube... fix**: a video added with *Add video...* now gets the metadata.txt of its scene in the list (before, only
  a metadata.txt next to the mp4 was found, and it uploaded with the file name as title). metadata.txt is read again when
  you press Upload, the status line shows which one a row uses, and Shadow asks before uploading a video without one.
- **1440p and 4K** in Quality (`1440p (QHD, 64 samples)`, `4K (UHD, 64 samples)`; 9:16 too). 20 s of 4K PNG is about 104 MB.

## 3.14
- **Upload from Claude**: Shadow's MCP server can now upload finished videos to YouTube, so Claude can make a video, render
  it and upload it in one go. `shadow_upload_preview` shows exactly what would be sent (title, description, tags, AI label,
  publish time, thumbnail) and sends nothing; `shadow_upload` uploads (Private by default) and is only used after you say
  yes; `shadow_upload_progress` / `shadow_upload_cancel` follow or stop it; `shadow_youtube` lists the signed-in channels.
  In the Assistant panel an upload always needs your **Allow once** click.
- **Projects**: **Project > Save project** keeps the list of scenes (in order), each row's narration and all the options
  in a `.shadow` file next to your scenes; **Open project** (or dropping the file on Shadow) brings it all back. Paths are
  stored relative to the project, so a moved or copied project folder still opens.
- **Edge as a fallback browser**: without Google Chrome, Shadow renders with Microsoft Edge (same engine, part of Windows);
  the setup bar then says *Edge (Chrome not found)*.
- **Self-test** button (and `Shadow.exe --selftest`): renders a 2-second test scene with a tone and checks it - browser,
  ffmpeg, frames, sound and the quality check - and says which step failed and what to install.
- **Cleanup**: temp folders left by a render that crashed (or a PC that switched off) and installer files of updates you
  already installed are removed when Shadow starts.

## 3.13
- **YouTube upload, more from `metadata.txt`**: `AI: yes` marks the video as *altered or synthetic content* (YouTube's AI
  label), the thumbnail Shadow saved (`<video>_thumb.jpg`, or `THUMBNAIL: cover.jpg`) is set on the video, and a `PUBLISH:`
  line with a date and time (`Thu 19 Nov 2026, 5:00 AM Sydney time`, `2026-11-25 05:00`) schedules it. The dialog has a
  Publish column and a checkbox for each. Scheduled videos only go public once your Google project has passed YouTube's audit.
- **Songs at -14 LUFS**: a video whose sound is a song file (Sound *Auto* finds `<scene>.mp3` next to it, or *External
  file*), or a scene in the Music folder, is now loudness-matched to -14 LUFS - YouTube's own playback level - instead of
  -15. Narrated and generated sound stays at -15. A scene can set its own target with
  `<meta name="shadow-lufs" content="-16">`. The QC check follows the target (target ±2).
- **Clear messages when a scene cannot render**: before the queue starts, Shadow lists the scenes that never set
  `window.__ready`, have no `window.seek(t)`, no `window.DURATION` or no `<canvas id="c">`, and asks whether to render
  them anyway. A scene without `window.__ready` now fails at once instead of after a 3-minute wait, and the other parts
  are checked as soon as the scene loads.
- **ffmpeg errors show their last 3 lines** instead of one.

## 3.12
- **Upload to YouTube** (**YouTube...** button): sign in once per channel in your browser, then upload the videos you just
  rendered - title, description (chapters), tags and Made for Kids from `metadata.txt`, Private by default, resumable with
  progress, a link to YouTube Studio when done. Uses the free YouTube Data API with your own Google Cloud project
  (setup in [docs/YOUTUBE.md](docs/YOUTUBE.md)); until that project passes YouTube's audit, uploads stay Private.
- **A Short and its video share one folder**: `short_ocean.html` (or `ocean-short.html`) rendered 9:16 now goes to
  `ocean\ocean_shorts.mp4`, next to `ocean\ocean.mp4`, instead of its own `short_ocean\` folder.
- **Folder option** (next to Save to): *Auto (Music / Video)* sorts every video into a main folder by itself - a scene that
  plays a song file next to it goes to `Music\`, everything else (own sound, narration, silent) to `Video\`. Or pick
  *Music*, *Video*, a folder you add with **New folder...**, or *None* (straight in Save to, like before).
- A scene can choose its folder with `<meta name="shadow-folder" content="Music">` (Auto follows it; nested like `Music/2026` works).

## 3.11
- **Check frames** button: select one or more scenes and get a contact sheet (16:9 and 9:16) in seconds, with page errors
  and frames that change between two draws of the same time (`seek(t)` not pure) listed - before a long render.
  Also `Shadow.exe --check scene.html`.
- **Time estimate**: a Time column (about how long each scene takes, the time left while it renders, how long it took) and
  "about 12 min · done ~15:40" for the whole queue, corrected with the speed measured while rendering.
- **Skip scenes already rendered** (on by default): a scene whose video is newer than the scene and its song / voice files
  is marked *Skipped (up to date)* instead of being rendered again as `_2`. Change the scene and it renders again.
- **Add folder...**: adds every `.html` / `.blend` scene in a folder (subfolders on request); dropping a folder works too.
- **Subtitles**: every narrated video gets a `.srt` file next to it, from the same word timings as the captions.
- **Assistant panel** (button *Assistant*): chat with Claude inside Shadow ("render this folder and check the quality")
  and watch its steps and reply as they arrive. It uses your Claude subscription through the installed Claude Code CLI;
  there is no API key. Claude can only read files and use Shadow's tools. Stopping a render needs your *Allow once*.
  Guide: [docs/ASSISTANT.md](docs/ASSISTANT.md).
- **Other AI clients:** setup for Claude Desktop, Cursor, VS Code (Copilot agent mode), Windsurf and Gemini CLI in
  [docs/MCP.md](docs/MCP.md), and an optional HTTP mode for the MCP server (`--http`). It listens on localhost only and is
  off by default.
- **Notification** when the queue ends (done / failed counts); click it to open the output folder. Can be turned off.

## 3.10 - 2026-11-19
- **Blender scenes:** add `.blend` files to the queue like `.html` scenes. Shadow runs your installed Blender in the
  background (Eevee, Cycles on the GPU, or Workbench) and uses the same encoding, sound (Auto), Shorts (a 9:16 camera picked
  by name) and quality check. Other frame rates are re-timed to 30 fps. Guide: [docs/BLENDER.md](docs/BLENDER.md).
- **Claude connection (MCP):** Claude can render scenes or folders, follow the progress, cancel, preview frames and read the
  quality report without opening the window; the result is the same as rendering in the app. Guide: [docs/MCP.md](docs/MCP.md).
- 3.8 and 3.9 were internal steps and were never released; their changes are in 3.10.

## 3.7 - 2026-11-18
- In-app updates install on the first try: the installer now waits until the old Shadow has fully closed (before, the
  first attempt could stay on the old version).

## 3.6 - 2026-11-18
- Loud songs pass the quality check: loudness and true peak are measured after the AAC encode and the track is turned
  down exactly as much as needed (never up) - about -15 LUFS and under -1 dBTP.
- Thumbnails: a scene that sets `window.THUMBNAIL_T` gets `<name>_thumb.jpg` (1280x720, or 720x1280 for Shorts).

## 3.5 - 2026-11-18
- Format Auto also renders 9:16 for names ending in `-short`, `_short` or ` short` (not only `short_` at the start).

## 3.4 - 2026-11-18
- Faster renders: frames go straight into ffmpeg (no frame files on disk), and the new **Capture** option *Fast (JPEG)*
  is about 2x faster with a very slightly softer picture. *Best quality (PNG)* stays the default.

## 3.3 - 2026-11-18
- Fixed gray stripes left between the panels when switching from Light to Dark.

## 3.2 - 2026-11-18
- Fixed: after an in-app update Shadow did not reopen ("Failed to load Python DLL").

## 3.1 - 2026-11-18
- The Light theme is a soft light gray instead of near-white.

## 3.0 - 2026-11-18 - first public release
- Installer: per-user install (no admin), Desktop and Start menu shortcuts, uninstall from Windows Apps; installs Google
  Chrome and ffmpeg with winget if they are missing.
- In-app updates: a *Check for updates* button; new releases install themselves.
- Render queue, 16:9 and 9:16 (Format Auto by file name), sound modes, narration with word captions, and a quality check
  report for every video.
