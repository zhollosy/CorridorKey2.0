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
