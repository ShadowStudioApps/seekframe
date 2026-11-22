# Seekframe privacy policy

*Last updated: 21 November 2026*

Seekframe is a free, open-source Windows desktop app that renders video scenes to MP4 files on your own computer and can
upload them to your own YouTube channel. It has no servers, no accounts and no analytics. This page explains what data
Seekframe touches and where it goes.

## What Seekframe sends over the internet

| When | To whom | What |
|---|---|---|
| Seekframe starts | GitHub (api.github.com) | A request for the latest release number, to show "Update to vX.Y". No personal data. |
| A scene loads web resources | The sites the scene itself names (for example a CDN for three.js or fonts) | Normal web requests made by the scene. |
| You press **Sign in...** in the YouTube dialog | Google (accounts.google.com, oauth2.googleapis.com) | The standard Google sign-in. You type your password on Google's own page; Seekframe never sees it. |
| You press **Upload** | YouTube Data API (googleapis.com) | The video file you chose and its title, description, tags, category, privacy and "Made for Kids" setting, the "altered or synthetic content" label and publish time if set, and the thumbnail image if one is set. |
| You sign in to a cloud account (Settings > Cloud accounts) | That provider (Google, Microsoft, Dropbox, Box or pCloud), through rclone | The provider's own sign-in in your browser; Seekframe never sees your password. rclone keeps the access token on your PC in `%USERPROFILE%\.shadow_cloud.conf`, encrypted with a key that Windows protects for your account (`%USERPROFILE%\.shadow_cloud_key.bin`). **Sign out** revokes it where the provider allows and deletes it. |
| You use **Cloud...** or *Also upload finished videos to* | That cloud account | Folder listings you open, the files you pick (downloaded to `Videos\Seekframe cloud`), and the finished videos you chose to upload. |
| You press **Get rclone** | GitHub (github.com/rclone/rclone releases) | A download of the official rclone release. No personal data. |
| You use the Assistant panel | Anthropic, through your own installed Claude Code | Your chat messages. Only when you use that panel. |
| You press **Make the video** in *New video (AI)* | Anthropic, through your own installed Claude Code | Your idea and the style and length you picked; Claude then reads the template scene and the narration it wrote in the new folder. The voice is made on your PC (Kokoro) and sends nothing. |
| You press **Fix the scene** in *AI...* | Anthropic, through your own installed Claude Code | The problems shown in the window (including your own words), the scene file and the files it loads that Claude chooses to read. |
| You press **Write YouTube text** in *AI...* | Anthropic, through your own installed Claude Code | A picture of 12 frames of that video, its file name, your note and the text of its scene. No YouTube or Google data is sent. |

If you choose **your own API key** (Settings > AI connections), the key is stored on your PC only, encrypted by Windows
for your account (`%USERPROFILE%\.shadow_ai_key.bin` for Anthropic, `%USERPROFILE%\.shadow_gemini_key.bin` for Google AI Studio; the
Gemini key is given to Gemini CLI only while Gemini does Seekframe's AI jobs in that mode), and is given to Claude Code only while that option is on, which sends
it to Anthropic with the AI requests above. **Remove key** deletes the file.

Nothing else is sent anywhere. The AI features run only when you press their buttons, use your own Claude subscription, and are covered by [Anthropic's privacy policy](https://www.anthropic.com/legal/privacy).

## YouTube and Google user data

Seekframe uses the YouTube API Services. By uploading with Seekframe you agree to the
[YouTube Terms of Service](https://www.youtube.com/t/terms), and Google's use of your data is governed by the
[Google Privacy Policy](https://policies.google.com/privacy).

- **Permissions requested:** `youtube.upload` (to upload the videos you choose) and `youtube.readonly` (to read your
  channel's name and ID, so the dialog can show which channel you are uploading to). Seekframe does not read, change or
  delete your existing videos, comments, playlists or any other data.
- **What is stored:** after you sign in, Seekframe stores your channel's name and ID and the OAuth refresh/access tokens in
  one file on your own computer: `%USERPROFILE%\.shadow_youtube_tokens.json`. It is never sent anywhere except back to
  Google to upload.
- **No sharing:** no YouTube or Google data is sent to the developer of Seekframe or to any third party. There is no
  developer server.
- **No other use:** the data is used only to upload the videos you choose, when you press Upload.
- **Deleting your data:** delete `%USERPROFILE%\.shadow_youtube_tokens.json` (or uninstall Seekframe and delete it), and
  revoke Seekframe's access at [Google account permissions](https://myaccount.google.com/permissions) → Seekframe → Remove access.
  Seekframe keeps no other copy.

Seekframe's use of information received from Google APIs adheres to the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
including the Limited Use requirements.

## Files on your computer

Seekframe keeps its settings in `%USERPROFILE%\.shadow_renderer.json` and a log in `%USERPROFILE%\shadow.log`. Your scenes and
videos stay where you put them.

## Contact

Questions or requests: open an issue at [github.com/ShadowStudioApps/seekframe/issues](https://github.com/ShadowStudioApps/seekframe/issues).
