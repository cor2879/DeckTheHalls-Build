# Deck the Halls — test Web build

This public repository contains compiled browser-build files, website hosting code and deployment tooling. The Unity project, editable artwork and private game source stay separate. Game availability depends on a successful export upload and deployment run.

Expected test URL, after the first successful deployment:
https://cor2879.github.io/DeckTheHalls-Build/

## One-time GitHub Pages setting

Open https://github.com/cor2879/DeckTheHalls-Build/settings/pages and select **Build and deployment → Source → GitHub Actions**. No custom domain or personal access token is required for the workflow. The connected editing tools cannot change that repository setting.

## Upload the WebGL export you already tested

Requires Git and Python 3.10 or newer. Use a separate checkout of this build repository:

```bash
git clone https://github.com/cor2879/DeckTheHalls-Build.git
cd DeckTheHalls-Build
python3 Tools/webgl_deploy.py stage "/absolute/path/to/your/finished/WebGL-export"
git add site
git commit -m "Upload tested WebGL build"
git push
```

Choose the **export folder containing index.html and Build/**. Do not point the command at the Unity project or copy the private repository here. Paths with spaces must be quoted. You can use the existing Chrome-tested export for the first deployment attempt; this repository does not rebuild Unity.

The helper copies index.html plus runtime files from Build/, StreamingAssets/ and TemplateData/ into generated site/. It ignores project folders and metadata, rejects source/art files inside runtime folders, and records sizes/checksums. Payloads over 90 MiB are split into Git-safe chunks and reassembled during deployment; use this helper instead of uploading large files through the GitHub website. Your original export is unchanged. Running stage again replaces the previous generated site/ payload and removes obsolete build files.

**Every subsequent push containing a staged build deploys the public test game.** Keep the Arcade-page link unpublished until hosted testing is complete. The URL and repository are public; the robots exclusion is not access control.

## What the workflow does

The Test deployment workflow validates the payload, reconstructs large files, prepares _site/, uploads only those runtime files and publishes them through GitHub Pages. On an empty setup it skips deployment until site/build-manifest.json is uploaded. It does not deploy this README, Python tools, tests or repository metadata.

Raw Unity Build/*.gz and *.br payloads are expanded on the runner and index.html references are updated for static hosting. This avoids requiring custom Content-Encoding headers, at the cost of larger published files. Existing *.unityweb assets retain Unity's built-in decompression fallback. StreamingAssets video URLs remain unchanged. Final output is checked against GitHub Pages' 1 GB published-site limit. A larger build will fail with a clear error instead of publishing an incomplete game.

Open the repository's Actions tab after pushing, then follow the deployment URL from the successful run. If the Pages step fails before publishing, first check the one-time Source setting above.

To validate locally without Unity:

```bash
python3 -m unittest discover -s Tools -p 'test_webgl_deploy.py'
python3 Tools/webgl_deploy.py validate
```

Optional: prepare exactly what Pages will host and serve it locally:

```bash
python3 -m pip install -r Tools/requirements-deploy.txt
python3 Tools/webgl_deploy.py prepare
python3 -m http.server 8080 --directory _site
```

Visit http://localhost:8080/ rather than opening index.html as a local file. The Brotli dependency is needed only for .br exports; the GitHub workflow installs it automatically. gzip preparation uses Python's standard library.

## Hosted test pass

- Fresh load in Chrome: loading progress, opening/logo, first interaction and audio.
- Keyboard/gamepad, fullscreen/window resize, tab focus, pause and reconnect.
- Tutorial/Lab and one complete Mall run through the results choices.
- Crowded fights, TV single-feed rotation and video pause/resume.
- Attack impact sounds, throwable gifts/props, food/token balance and score/lives.
- Settings, scores, badges and puzzle progress after refreshing.
- Check a second browser/device, the browser console and failed network requests.

Browser saves are tied to the site's origin. The hosted test starts with separate saved settings/progress from the Editor or a localhost test. A successful deployment is not the same as a completed hosted playtest.

## References

- Pages workflow setup: https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
- Pages limits: https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
- Git file-size limits: https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github
- Unity compressed builds: https://docs.unity3d.com/6000.0/Documentation/Manual/webgl-deploying.html

## Website presentation

`Web/game-viewport.css` owns the responsive 16:9 game viewport. Preparing an export adds this style after the export's styles, fits the game to both window dimensions, and centers the unused space as letterboxing. Unity continues matching its render resolution to the canvas. The staged, checksummed export remains unchanged; website changes do not require a Unity rebuild.

After pulling website updates, run `python3 Tools/webgl_deploy.py prepare` again and refresh your locally served page. Future Pages deployments apply the same presentation automatically.
