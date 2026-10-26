# PixSift test plan

For testers checking a PixSift release. Installation steps are in [TESTING.md](../../TESTING.md); this plan
lists **what** to test and **what should happen**.

- **Release under test:** the [latest release](https://github.com/jha-pravin/pixsift/releases/latest) (currently v0.4.0)
- **Report:** one [bug report](https://github.com/jha-pravin/pixsift/issues/new?template=bug_report.yml) per
  problem, plus one [test session report](https://github.com/jha-pravin/pixsift/issues/new?template=test_report.yml)
  when you finish
- **Privacy:** you never need to share your own photos. Describe what you saw; use screenshots of the app only
  if you're comfortable with them. Everything PixSift does stays on your computer.

## Test environments

Test on whatever you have; note it in your report.

| Platform | Download | Priority |
|---|---|---|
| Windows 10 / 11 | `PixSift-windows.zip` | **High**: least tested so far |
| macOS, Apple silicon (M1 or later) | `PixSift-mac-arm64.zip` | Medium |
| macOS, Intel | `PixSift-mac-intel.zip` | Medium |

A good test set: one or two folders with a few hundred to a few thousand pictures, including people (ideally
the same people across several photos and years), a few documents or receipts, screenshots, some HEIC (iPhone)
photos, and a couple of duplicate copies.

## Test cases

Mark each case **Pass / Fail / Blocked / Not tested** in your test session report. "P1" cases matter most.

### A. Install and first launch

| ID | P | Steps | Expected |
|---|---|---|---|
| A1 | P1 | Unzip and open PixSift (follow TESTING.md for the first-launch security prompt). | The app opens to a **Welcome to PixSift** screen with the logo. |
| A2 | P2 | Quit and reopen PixSift. | It opens straight to the Dashboard (no welcome screen once pictures exist). |
| A3 | P2 | Check the app icon in the Dock / taskbar and the window title. | PixSift logo (viewfinder with a face and a coral spark); title "PixSift". |

### B. Scanning

| ID | P | Steps | Expected |
|---|---|---|---|
| B1 | P1 | **Sources → Choose folders…**, select **two** folders at once (⌘/Ctrl-click), then **Scan now**. | Both folders appear in the list. Scanning starts. |
| B2 | P1 | Watch the first scan. | First a one-time model download (about 128 MB) with progress, then "Scanning and analysing" with a progress bar, speed, time left and the current file. The top bar shows the same progress. |
| B3 | P1 | Let it finish. | "Last run: done". The Dashboard shows picture counts. No crash or freeze. |
| B4 | P2 | Note how many pictures and how long the first scan took. | Rough guide: 10+ new photos per second on a recent laptop. Report your numbers either way. |
| B5 | P2 | Click **Scan now** again without changing anything. | Finishes quickly; everything shows as unchanged. |
| B6 | P2 | Copy a few photos into a scanned folder and rescan. | Only the new ones are processed. Exact copies of existing photos are reused instantly ("duplicates" count). |
| B7 | P3 | Add a folder by typing or pasting several paths (one per line) into the path box. | Each path becomes its own entry; duplicates are ignored. |

### C. Dashboard and picture types

| ID | P | Steps | Expected |
|---|---|---|---|
| C1 | P1 | Open the Dashboard. | Cards for People, Photos, Documents, Screenshots, Graphics with counts and previews. |
| C2 | P1 | Open **Documents** and **Screenshots**. | Mostly correct pictures in each. Note clear mistakes (wrong type) in your report. |
| C3 | P2 | In the viewer's info panel (press **I**), change a picture's **Type**, then rescan. | Your choice sticks after the rescan. |

### D. People and faces

| ID | P | Steps | Expected |
|---|---|---|---|
| D1 | P1 | Open **People**. Under "Who are these people?", name two or three groups. | Each named group becomes a person card. |
| D2 | P1 | After naming, look at the message and the person's card. | PixSift recognises more photos of that person automatically ("to review" badge). |
| D3 | P1 | Click a person. | Their page shows **All photos** with the total and a month-by-month timeline, plus a year chart and facts. Scrolling loads more photos without jumping back to the top. |
| D4 | P1 | On a person's page, **Review faces** → remove a wrong face (×), then **Confirm** the automatic matches. | The wrong face leaves; confirmed faces lose the dashed ring. |
| D5 | P1 | Check that no group mixes two different people (especially look-alike relatives or children). | Each group is one person. **Report any mixed group**; this matters a lot. |
| D6 | P2 | On a group of someone you don't want to tag, click **Hide person**. | The group disappears and appears under **Hidden people** at the bottom. |
| D7 | P2 | Under Hidden people, type a name and press **Name**. | They become a normal person with all their photos. |
| D8 | P2 | Change "Ask about people in at least N photos". | The number of groups shown changes. |
| D9 | P2 | Merge two people (person page → Merge into…), rename one, remove a name. | Each works; removing a name returns the faces to the questions. |

### E. Viewer and editing

| ID | P | Steps | Expected |
|---|---|---|---|
| E1 | P1 | Open any picture. Use ←/→, scroll to zoom, drag to pan, **F** for face boxes, **I** for info, **Esc** to close. | All work smoothly. Info shows date, camera, size, location (if any), folder. |
| E2 | P1 | In the info panel, click a person's **name**. | Opens that person's page with all their photos. |
| E3 | P1 | Click a face box on the picture and name or rename it. | The name appears on the box and in the info panel. |
| E4 | P1 | **Show in Finder / Show in Explorer** (folder icon). | The file's folder opens with the file selected. **On Windows, please check carefully.** |
| E5 | P2 | **Open in default app**. | The picture opens in your usual image viewer. |
| E6 | P1 | Press **E**: rotate, crop (try 16:9), change brightness, **Save** (new copy). | A `…_edited` file appears next to the original; the original is unchanged. |
| E7 | P2 | Edit again with **Replace original** (tick the confirmation). | The original changes; a backup exists in PixSift's data folder. |
| E8 | P3 | Add a tag to a picture, then search for it in the top search box. | The picture is found. |

### F. External drive (if you have one)

| ID | P | Steps | Expected |
|---|---|---|---|
| F1 | P2 | Plug in a USB drive with pictures while PixSift is open. | Within a few seconds: "Drive … connected. Find pictures on it?" |
| F2 | P2 | Click **Scan drive**, let it finish, then unplug the drive. | Its pictures stay visible with a drive badge; opening one shows a small preview and "connect the drive" note. |
| F3 | P2 | Plug the drive back in. | It re-scans automatically; new photos on it are found. |

### G. Library and filters

| ID | P | Steps | Expected |
|---|---|---|---|
| G1 | P2 | Library: filter by type, one person, then add a second person ("+ with…"). | Only pictures matching all filters show. |
| G2 | P2 | Filter by folder and by a month range; sort oldest first. | Results and order update correctly. |
| G3 | P3 | Tick **Duplicates**. | Exact copies are listed together. |

### H. Robustness and privacy

| ID | P | Steps | Expected |
|---|---|---|---|
| H1 | P1 | Quit PixSift in the middle of a scan; reopen it. | It continues analysing where it stopped without a new scan. |
| H2 | P2 | Put your computer to sleep during a scan; wake it. | The scan continues or finishes; no freeze. |
| H3 | P2 | Open a browser at `http://127.0.0.1:<any port>` guesses, or another app's address. | No PixSift data is reachable without the app (it needs its own sign-in token). Optional for technical testers. |
| H4 | P3 | Turn off Wi-Fi after the first scan and use the app. | Everything works offline. |

## Done when

- All **P1** cases pass on at least one Windows PC and one Mac, and
- no open bug report is marked **Blocker** or **Major**.

## Uninstall

See "Removing PixSift" in [TESTING.md](../../TESTING.md). Your own pictures are never changed by uninstalling.
