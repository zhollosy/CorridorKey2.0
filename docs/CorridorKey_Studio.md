# CorridorKey Studio (desktop GUI)

CorridorKey Studio is a Tkinter front end for `infer.py`. It adds a render
queue, a preview/compare viewer, a per-job settings inspector and a chroma-key
hint maker on top of the command-line tool. Every render still runs
`infer.py` in its own process, so results are identical to the CLI.

## Starting it

- Double-click `CorridorKey_Studio.bat`, or drop clips/folders onto it.
- Or run `venv\Scripts\python corridorkey_studio.py [clips or folders...]`.

Optional drag and drop from Explorer needs `tkinterdnd2`
(`pip install -r requirements-gui.txt`).

## Workflow

1. **Add clips**: `Ctrl+O` for video files, `Ctrl+Shift+O` for a folder. A
   folder of videos is added as a batch. A folder of frames (or one with an
   `Input` subfolder) becomes an image-sequence job. Companion hints are
   detected automatically: `<clip>FrameHint.png` for a first-frame matte,
   `<clip>_AlphaHint.mp4` or an `AlphaHint` subfolder for a hint video.
2. **Select a job** and adjust it in the inspector tabs (Hint, Output,
   Memory, Range, Advanced). With several jobs selected, a change applies to
   all of them. With nothing selected, you are editing the defaults for newly
   added clips.
3. **Preview**: scrub the input with the slider or arrow keys. After a render,
   pick `alpha`, `fg`, `checker` or `cutout` in *View* and tick *Compare with
   input* for a side-by-side.
4. **Render**: `F5` runs every enabled, queued job; `Ctrl+F5` runs only the
   selection. *Stop After Current* finishes the running clip, *Abort*
   (`Shift+F5`) kills it.

## Useful extras

- **Make Hint**: builds a first-frame matte from a quick green/blue chroma
  key with threshold, softness, shrink/grow and clean-up controls, saves it as
  `<clip>FrameHint.png` and assigns it to the job.
- **Copy Command Line** (`Ctrl+Shift+C`): the exact `infer.py` call for a job,
  handy for render farms or scripts.
- **Queues**: save/load `.ckqueue` files; the last queue is restored on start.
- **Tools menu**: environment check, model smoke test, weight download/repair,
  feature-cache cleanup.
- **Status bar**: live GPU name, VRAM, utilisation and temperature.

## Preferences (`Ctrl+,`)

- *General*: Python interpreter, `infer.py` location, feature cache folder,
  output location (next to each clip or a fixed folder) and folder-name
  pattern, skip existing outputs, hint auto-detection, notifications.
- *Encoding*: ffmpeg binary, codec, CRF, preset, pixel format, bitrate,
  threads, EXR pixel type.
- *Performance*: stage-2 batch, low-VRAM tuning knobs, GPU poll interval.
- *Appearance*: dark/light theme, log font size, log history.

Settings live in `%APPDATA%\CorridorKeyStudio\config.json`.

## Notes

- Each job loads the model again (a few seconds when the weights are in the
  OS file cache, longer from a cold disk).
- The GUI code is in `ck_gui/`: `app.py` (main window), `inspector.py`,
  `preview.py`, `dialogs.py`, `runner.py` (worker threads), `jobs.py`
  (discovery and command building), `config.py`, `theme.py`.
