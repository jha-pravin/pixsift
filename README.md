# PixSift

> Source-available, free for personal and other noncommercial use ([PolyForm Noncommercial 1.0.0](LICENSE.md)).

Local-first picture organizer for macOS and Windows. PixSift scans your folders and drives for pictures,
sorts them into **photos, documents, screenshots and graphics**, finds the **faces** in them, lets you name
each person once, and then shows every picture of that person on a **timeline**. All recognition runs on
your computer; nothing is uploaded. Originals are never changed unless you explicitly choose "Replace original".

## Features

| Area | What you get |
|------|--------------|
| **Scan** | Pick folders or whole drives (native multi-folder picker in the desktop app). Incremental re-scans; deleted files drop out; duplicates detected. JPG, PNG, HEIC/HEIF, WEBP, GIF, TIFF, BMP. |
| **External drives** | A newly connected drive gets one question: "Find pictures on it?" Pictures on an unplugged drive stay in your library (thumbnails, faces, names) marked with the drive's name, so a person's timeline still shows them. Reconnect it and new pictures are found automatically. Drives are recognised by their volume ID, so a new mount point or drive letter doesn't matter. |
| **Dashboard** | Counts and previews per type, people, unnamed face groups, recent pictures, duplicates. |
| **Picture types** | Automatic: Photo / Document / Screenshot / Graphic (on-device CLIP model + file hints), plus "has people". You can correct any picture's type; re-analysis keeps your choice. |
| **Faces & people** | Faces are detected and grouped automatically. Name a group once ("Who is this?"), or click a face in any picture. PixSift then recognises that person in other photos: confident matches are named automatically (dashed ring, "to review"; confirm in one click), less certain ones are suggested ("Is this Mom?"). Merge, rename, "Not this person", ignore strangers. **Hide person** stops PixSift asking about someone (they're still recognised quietly); name them later from *Hidden people* and every photo found meanwhile comes along. Only people in at least N photos are asked about (default 3). |
| **Person timeline** | Click a name: all their pictures by month, a by-year chart, date range, cameras, folders, places (GPS), and who they're often pictured with. |
| **Viewer** | Full-screen, ←/→, zoom and pan, filmstrip, face boxes, info panel (date, camera, size, location, folder), tags, related files (duplicates, edited copies). |
| **Show in Finder / Explorer** | From every thumbnail and the viewer, opens the folder with the file selected. Also Open with default app and Copy path. |
| **Basic editing** | Rotate, flip, crop (free or 1:1, 4:3, 3:2, 16:9), brightness, contrast, saturation. Saves a new copy next to the original by default (`IMG_1234_edited.jpg`); "Replace original" keeps a backup. JPEG rotate/flip is lossless (only the orientation tag changes). Names and tags carry over to edited copies. |
| **Search & filters** | File name or tag search, type, one or more people ("pictures with Mom *and* Dad"), tag, folder, month range, duplicates, sort. |

## Download

Get the app for Windows, Apple-silicon Macs or Intel Macs from the
[latest release](https://github.com/jha-pravin/pixsift/releases/latest). The [testing guide](TESTING.md) covers
installing the unsigned builds and what to try.

## Running from source

### Desktop app (recommended)

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[desktop]"
cd ../frontend && npm install && npm run build
cd ../backend && .venv/bin/python -m pixsift.desktop
```

### Build an installable app

Releases are built by GitHub Actions (`.github/workflows/build.yml`). Every push runs the tests on macOS and
Windows and builds all three apps; each build checks itself with `PixSift --self-test`. Pushing a version tag
publishes a release:

```bash
git tag v0.2.1 && git push origin v0.2.1
```

To build locally instead: `packaging/build_mac.sh` gives `dist/PixSift.app`, and `.\packaging\build_windows.ps1`
(PowerShell, Python 3.11+, Node 20+) gives `dist\PixSift\PixSift.exe`. Builds are unsigned; see
[TESTING.md](TESTING.md) for opening them.

### Browser mode (development)

```bash
cd backend && .venv/bin/python -m pixsift      # engine + built UI; opens the browser with a sign-in link
```

The link printed at startup ends in `?token=…`. That's the per-launch access token (see [SECURITY.md](SECURITY.md)).
For a hot-reloading UI, start both with the same fixed token:

```bash
PIXSIFT_TOKEN=dev PIXSIFT_NO_BROWSER=1 backend/.venv/bin/python -m pixsift
PIXSIFT_TOKEN=dev npm --prefix frontend run dev   # http://localhost:5173
```

## First run

1. **Sources**: add folders (Pictures is pre-selected) or drives, then press **Scan now**.
2. The first scan downloads the AI models once (about 195 MB, from Hugging Face and the OpenCV model zoo). Each
   file is checked against a pinned SHA-256. After that PixSift works fully offline.
3. **People**: name the face groups. Every picture of that person is then one click away.

Speed on an Apple-silicon laptop is roughly 50 ms per picture for analysis, i.e. about 20,000 pictures per
15–20 minutes. The first scan takes longest; re-scans only process new or changed files.

## How recognition improves over time

- **Closest matches, not averages.** A new face is compared with each person's 3 most similar *confirmed* faces,
  so a photo of a child at 10 matches photos of them around 10, not a blend of every age.
- **Time-aware.** Similarity counts up to 30% less for photos taken years apart, so recent photos weigh more.
- **Learns from corrections.** "Not <person>" makes that face a counter-example: faces closer to it than to
  the person (a sibling, a lookalike) are no longer matched to them.
- **No self-reinforcement.** Only faces you named or confirmed are used as references. Automatic matches count
  once you confirm them, so mistakes don't snowball.
- **Thresholds** (in `backend/pixsift/faces.py`): suggest at a score of 0.45; name automatically at 0.60 when the
  match beats the next-best person by 0.10.

## Where data lives

The database, thumbnails, face crops, models and edit backups are stored in
`~/Library/Application Support/PixSift` on macOS and `%LOCALAPPDATA%\PixSift` on Windows. Override it with
`PIXSIFT_DATA_DIR`. To start over, quit PixSift and delete that folder. Your pictures are not affected.

## Architecture

```
frontend/   React + TypeScript + Vite UI (HashRouter)
backend/    Python engine (FastAPI), localhost only
  pixsift/scanner.py     folder walk with skip rules
  pixsift/media.py       quick hash + EXIF + thumbnail (one image open)
  pixsift/analyzer.py    faces: OpenCV YuNet + SFace; picture type: CLIP ViT-B/32 (ONNX, quantised)
  pixsift/faces.py       HDBSCAN grouping, name suggestions, carry-over of names
  pixsift/pipeline.py    background job: models → scan → analyse → group
  pixsift/editor.py      edits (lossless JPEG orientation, copy/backup handling)
  pixsift/api.py, people_api.py   HTTP API
  pixsift/desktop.py     native window (pywebview) + folder picker
packaging/  PyInstaller spec, icon, build scripts
```

## Scanning rules

- Skipped: hidden folders, `Library`, `AppData`, `node_modules`, app bundles, and Photos/Lightroom
  libraries (they hold derivatives that would show up as duplicates). Files under 10 KB are ignored.
- Taken date comes from EXIF `DateTimeOriginal`, falling back to the file's modification time (shown as "file date").
- Duplicates use a quick hash: size + first and last MiB.

## Known limitations

- Faces that are sideways or upside-down in the stored picture (wrong orientation) aren't detected.
- Picture types are a best guess. Logos and illustrations are the least reliable; correct them from the viewer.
- GPS locations are shown as coordinates. There's no offline place-name lookup yet.
- The Windows build is tested automatically, but has had little hands-on use so far. Feedback is welcome.

## Tests

```bash
cd backend && .venv/bin/pytest
```

The people/analysis tests need the models. They use `PIXSIFT_MODELS_DIR` or the repo's `.demo-data/models` folder,
and are skipped when the models aren't present.

## Security

PixSift is local-only: the engine listens on 127.0.0.1, every request needs a per-launch access token, and
cross-site requests are refused. Nothing is uploaded. See [SECURITY.md](SECURITY.md) for the design and how to
report a vulnerability.

## License

PixSift is **source-available** under the [PolyForm Noncommercial License 1.0.0](LICENSE.md).

- ✅ Free to use, study, modify and share for personal, educational, research, charitable and other
  noncommercial purposes.
- ❌ Commercial use, including selling PixSift or a modified version, or bundling it into a paid product or
  service, isn't permitted.
- For commercial licensing, contact the author: [@jha-pravin](https://github.com/jha-pravin).

Copyright © 2026 Pravin Jha. Contributions are covered by [CONTRIBUTING.md](CONTRIBUTING.md). Third-party
models and test images are listed in [NOTICE.md](NOTICE.md).
