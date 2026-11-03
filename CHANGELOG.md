# Changelog

## [Unreleased]

### Added
- **CorridorKey Studio**, a desktop GUI (`ck_gui/`), started with `CorridorKey_Studio.bat` or `corridorkey_studio.py`.
- Render queue: batch folders, image sequences, enable/disable, reorder, duplicate, run all or only selected, stop after current, abort.
- Live progress per clip with stage, elapsed time and ETA, plus overall queue progress in the status bar and window title.
- Settings inspector for hints, outputs, memory, frame range and advanced options; edits apply to all selected jobs.
- Preview with a frame scrubber and side-by-side compare of the input against the alpha, fg, checker or cutout output.
- Chroma-key hint maker that saves a `<clip>FrameHint.png` and assigns it to the job.
- Automatic detection of companion `FrameHint` / `AlphaHint` files, matching the drag-and-drop launcher.
- Preferences dialog for runtime paths, output location and naming, ffmpeg encoding, low-VRAM tuning and appearance.
- Save/load queue files, restoring the last queue on start, and a recent-queues menu.
- Tools menu: environment check, model smoke test, weight download, feature-cache cleanup.
- GPU status (VRAM, load, temperature) in the status bar.
- Optional drag and drop from Explorer through `tkinterdnd2` (`requirements-gui.txt`).
- Dark and light themes, keyboard shortcuts (F1), and a "Copy command line" action.
- Guide in `docs/CorridorKey_Studio.md`.
- The Help menu shows the License and User Guide in a built-in scrollable viewer instead of opening local files.
- The Help menu links to the official CorridorKey project on GitHub, and the About box no longer shows local file paths.
- Radio buttons and checkboxes now show a clear green dot or check when selected; before, the selected option looked empty.
- The preview's frame slider and step buttons stay visible when the preview panel is short; before, they could be pushed out of view.
- The preview and queue open with a sensible share of the window instead of being crowded by the settings tabs.
- The Progress column widens with the window, so "100%" is no longer cut off.
- Before each render, the log warns when the feature-cache drive has less than 8 GB free.
- A full disk now fails with a plain explanation and points to the Feature cache folder setting, instead of a raw `Errno 28`.

- New **Wrap lines** option for the log, as a checkbox on the log toolbar and under View > Wrap Long Log Lines. Wrapped lines are indented under the message so timestamps stay in their own column. With wrapping off, a horizontal scrollbar appears, and the choice is remembered.

- The README shows a screenshot of CorridorKey Studio after keying the synthetic sphere test clip (`docs/images/corridorkey_studio.png`). PNGs in `docs/images/` are exempt from the repo-wide `*.png` ignore rule.
- The README's CorridorKey Studio section now lists all GUI features, how to start the app and enable drag and drop, and the disk-space advice.
- The README setup notes that Python 3.10 to 3.12 is required, because `numpy<2` cannot be installed on 3.13.

### Local developer setup (not committed)
- `.claude/starter.json` tells ClaudeStarter to launch CorridorKey Studio with **Run**.
- `.vscode/tasks.json` adds VS Code tasks: run the GUI (default build task), the interactive launcher, keying a clip, a 24-frame quick test, the model smoke test, a compile check, the weight download, and venv setup/install.
- Both folders are git-ignored, so they stay on this machine.
- A git-ignored `samples/` folder holds third-party test footage, which must not be redistributed.
