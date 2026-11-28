# Rafii local video editor

On this Mac, double-click **Open Rafii Video Editor.command**. The launcher opens the editor at [localhost](http://localhost:47632/local-studio). When the previous Studio is already using that address, save any open work first. The launcher identifies the existing staging process, builds the new browser bundle and offers to switch. Pressing Return keeps the previous Studio running. The signed-in workspace remains available at [Video Studio](http://localhost:47632/app/creative?workspace=1).

## Make and revise a cut

1. Open **Media** and choose a reference you are allowed to analyze. Run **Analyze reference**. The contact sheet can show measured shots or sample a continuous take at regular intervals. Each available image shows its decoded source time.
2. Save your brief in **Blueprint**, then generate a shot plan. Local brand and audience fields belong to this project. The signed-in workspace supplies the approved Brand Brain, Creative Memory, model quotes and generation approvals.
3. Import your original production clips in **Media**. Assign a clip to each scene, edit its trim and caption, and move or remove scenes as needed. An optional authorized WAV, MP3, or AAC soundtrack replaces clip audio across the cut. A short track ends in silence.
4. Preview and export use the same MP4. Save the project JSON to keep editing later. Reopening an imported project requires its original files. The editor checks their content hashes.
5. After rendering, **Check Library destination** identifies your signed-in staging account and workspace. The subsequent **Save MP4** button uploads the selected render using Rafii's existing resumable Library workflow. A verified asset opens in the native Creative Studio as a reference. Authentication, membership, MFA, budget and publication controls remain with their existing services.

## Sample edit

Open [Rafii Studio Preview.html](Rafii%20Studio%20Preview.html) to compare two four-second cuts of the bundled timer study. The local editor opens the sample project when there is no saved edit to restore.

## Build and test

Use Node 24, Python 3 and local FFmpeg/FFprobe. Install dependencies on a fresh checkout with `npm --prefix web ci`. The launcher also supports Finder's system Python. The FFmpeg build must support the `fd` input protocol and H.264, AAC, JPEG and MP4 handling. The local editor can run without a database. Signed-in workspace features require the [native Rafii setup](../docs/creative-intelligence/validation.md).

Run from the repository root.

```sh
'app/Start Rafii Studio.command' --build-editor
python3 -m unittest app.test_launch_studio app.test_studio_media
node --test --test-concurrency=1 app/test-studio-http.cjs app/test_studio_editor.cjs app/test_studio_contact_sheet.cjs app/test_studio_workspace.cjs
```

From an active Craft Anything project, run `craft-anything-cli --project investigation.cany rebuild-check --project "$PWD"` for the Craft check.

The complete native Next.js rebuild remains available via `'app/Start Rafii Studio.command' --build` with the staging launcher closed. For the existing synthetic workspace, `'app/Start Rafii Studio.command' --local --edit` opens the same editor. Staging Library transfer requires the connected staging workspace.

Reproduce the private example with the locally authorized original Veo take. Each invocation uses a new private output directory under `app/.local-evidence/`.

```sh
node app/reproduce_studio_example.cjs docs/creative-intelligence/examples/veo-experiment-20261127.mp4
```

## Implementation and provenance

- `serve-studio.cjs` adds the loopback editor routes alongside the native Rafii Next server. `studio-http.cjs` accepts size-bounded same-origin requests and serializes local media work. The media subprocess receives a minimal environment.
- `studio_media.py` uses Rafii's existing analyzer, source-frame decoder, blueprint adapter and renderer. Its soundtrack step decodes local audio and remuxes it with the original picture and caption packets. An analysis grant permits reading timing and thumbnail evidence. Production clips are selected separately.
- `studio-editor.js` owns project files, session edits, undo and file relinking. `studio-workspace.js` reuses the existing Supabase client library, Rafii API client, workspace permission check, media checks and signed resumable uploader. A cut can be edited locally before a user chooses a destination account.
- The browser bundle uses the repository's existing Next.js compiler and TypeScript. Thumbnails use the existing Pillow path where available and the installed FFmpeg tools otherwise. This change adds no package or bundled model. The first-party web theme and timer media are served from their existing owners. The private historical Veo take is outside the sample allowlist.
- The independent reference study uses Hypit v0.3.5. See the [capability comparison](../docs/creative-intelligence/parity.csv) and [native module ownership](../docs/creative-intelligence/architecture.md).

## Remaining acceptance

The next generation run needs cleared brand assets and a newly authorized model request on an entitled provider, followed by first and revised outputs across the five specified categories. Local cut comparison and timing tests demonstrate a subset of the reference inventory. The matrix retains the outstanding groups. The team still needs live signed-in Library upload/playback, commercial licensing review and the complete end-to-end measurements before release.
