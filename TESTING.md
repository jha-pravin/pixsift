# Testing PixSift

Thanks for trying PixSift! It takes about 15 minutes. Everything runs on your computer: your pictures, faces
and names are never uploaded.

**Testers:** this page covers installing and a quick tour. For a full pass, use the
[test plan](docs/testing/TEST_PLAN.md) (numbered test cases with expected results), and report with the
[bug report](https://github.com/jha-pravin/pixsift/issues/new?template=bug_report.yml) and
[test session report](https://github.com/jha-pravin/pixsift/issues/new?template=test_report.yml) forms.

## 1. Install

Download the file for your computer from the
[latest release](https://github.com/jha-pravin/pixsift/releases/latest):

| Your computer | File |
|---|---|
| Windows 10 / 11 | `PixSift-windows.zip` |
| Mac with Apple silicon (M1 or later) | `PixSift-mac-arm64.zip` |
| Mac with Intel processor | `PixSift-mac-intel.zip` |

Not sure which Mac you have? Apple menu → **About This Mac**: "Chip: Apple M…" means Apple silicon.

**Mac**
1. Double-click the zip to unzip it, then drag **PixSift** into **Applications**.
2. Open PixSift. macOS will say it can't verify the developer, because the test build isn't signed yet.
3. Open **System Settings → Privacy & Security**, scroll down to the PixSift message, click **Open Anyway**,
   and confirm. You only need to do this once.

If macOS instead says the app is "damaged", open Terminal and run
`xattr -dr com.apple.quarantine /Applications/PixSift.app`, then open it again.

**Windows**
1. Right-click the zip → **Extract All…**. Keep the whole **PixSift** folder together.
2. Open the folder and double-click **PixSift.exe**.
3. If a blue "Windows protected your PC" box appears, click **More info → Run anyway**.

## 2. Try these

1. **Sources**: click **Choose folders…** and pick one or two folders with pictures (a few hundred is plenty;
   hold ⌘ on Mac or Ctrl on Windows to choose several). Click **Scan now**. The first scan downloads the AI
   models once (about 128 MB), then shows progress.
2. **Dashboard**: are photos, documents, screenshots and graphics sorted sensibly?
3. **People**: give a few face groups a name. Then:
   - Does PixSift find the same person in other photos ("recognised automatically")?
   - Open the person: is the timeline right? Confirm or remove the automatic matches.
4. **Viewer**: open a picture. Use ←/→ to move through pictures, scroll to zoom, press **I** for the info panel
   and **F** for face boxes. Click a face to name it.
5. **Show in Finder / Explorer**: the folder icon on a picture should open its folder with the file selected.
6. **Edit**: press **E** in the viewer. Rotate, crop and change brightness, then **Save**. A new
   `…_edited` copy should appear next to the original, and the original should be unchanged.
7. **Library filters**: filter by type, person (try two people together), folder and month range.
8. **External drive** (if you have one): plug it in, then answer "Find pictures on it?" with **Scan drive**.
   Unplug it: its pictures should stay visible, marked as on that drive. Plug it in again: new pictures are found.
9. **Hide person**: on People, hide someone you don't want to tag. They should disappear from the questions and
   appear under **Hidden people**, where you can name them later.

## 3. Tell us how it went

Please file a [bug report](https://github.com/jha-pravin/pixsift/issues/new?template=bug_report.yml) for each
problem and a [test session report](https://github.com/jha-pravin/pixsift/issues/new?template=test_report.yml)
when you're done (or reply to whoever sent you this). Useful details:

- your computer and system version (e.g. "MacBook Air M2, macOS 15.3" or "Windows 11 laptop");
- roughly how many pictures you scanned and how long the first scan took;
- anything that was confusing, wrong or slow, especially wrongly grouped or wrongly recognised faces and
  wrongly sorted pictures (a description is enough; you don't need to share private pictures);
- if something broke: what you clicked just before, and a screenshot of the error.

## Removing PixSift

Delete the app, then delete its data folder (library, thumbnails and models):

- **Mac:** `~/Library/Application Support/PixSift` (Finder → Go → Go to Folder…)
- **Windows:** `%LOCALAPPDATA%\PixSift` (paste into the File Explorer address bar)

Your own pictures are never changed or deleted by uninstalling.
