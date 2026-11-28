# Reproduce the first wave

## Use the workspace

1. Open **Create → Video Studio** in a Rafii workspace with the private video Library enabled. An existing verified video also has a Video Studio action in Library.
2. Upload or select an MP4/MOV you may analyze, confirm its rights, and describe the new campaign. Select Instagram, TikTok or YouTube and the output orientation. Review the measurements, proposed original shot directions, suggested captions and pinned brand context.
3. For a zero-provider-cost edit, assign a separately authorized original clip to each scene and save. For a generated shot, an eligible workspace approver reviews that scene's quote and deliberately submits the request. Check the saved operation for updates.
4. Render the project and open the private export. Change the first scene, save a new revision and render again. The saved history opens the earlier export. The first version's approval does not authorize another generation.

The supplied timer study is suitable for steps 1–4 using separately authored original clips. Choose `reference.mp4` for analysis and `original-1.mp4` through `original-3.mp4` for footage. Replace only scene one's clip with `revised-intro.mp4` to try the revision. A local upload and render still require the normal Library permission and capacity rules. [Sample media and measurements](examples/README.md)

## Local dependencies and checks

Use the project's Python 3.12 environment and the requirements in the repository root. Use the project-supported Node 24 line and install web packages from the existing lockfile. A worker running the local path needs FFmpeg and FFprobe with the seekable `fd` protocol, the MOV demuxer, H.264 encoder, AAC and MP4 timed text. Offline English overlay detection can use Tesseract with English trained data. A missing optional recognizer produces an unavailable measurement. The project has no new required JavaScript, Python or external SDK dependency.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python -m unittest \
  test_creative_video_blueprint test_creative_video_inventory test_creative_video_media \
  test_creative_video_recovery test_creative_video_reference_signals test_trend_media_runtime test_video_uploads \
  test_hosted_storage_video test_brand_brain_memory test_postriff_phase2_hosted \
  test_dev_hosted_resumable test_consumer_deployment test_postriff_image_runtime \
  test_postriff_hosted_deployment test_postriff_billing
```

Run the new OCR suite alongside those tests on a host with English Tesseract. The media example script accepts an empty output directory and verifies both exports. To reproduce the SQL workflow use the normal disposable PostgreSQL harness from the repository root. It initializes its own local cluster and requires PostgreSQL 17 utilities, permission for local shared memory and a loopback socket. It creates its own roles, synthetic credit policy and funding, Library and provider test double.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python \
  scripts/postriff_pg_suite.py postgres_creative_video
python3.12 scripts/creative_video_media_example.py /path/to/an/empty/output
```

The optional version of the same scenario runs inside one in-memory PostgreSQL instance without a socket. It accepts a separately supplied, extracted copy of `@electric-sql/pglite@0.5.8`. The fixture does not install this tool or add it to product dependencies. The sequential engine exercises real SQL, migrations, RLS grants, workspace endpoints, the usage ledger, media bytes and durable records. Cross-connection serialization needs the ordinary PostgreSQL environment. [PGlite source and licensing](https://github.com/electric-sql/pglite)

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python \
  tests/phase2/creative_video_embedded.py --pglite /path/to/extracted/package \
  --node /path/to/node --receipt /path/to/integration-receipt.json
cd web
npm ci
node --test tests/creative-video.test.mjs tests/creative-video-ui.test.cjs
node node_modules/typescript/bin/tsc --noEmit --incremental false
npm run build
```

The standard web build requests the existing Google fonts. In this restricted workspace an offline webpack build used the same lockfile, the same theme configuration and cached, byte-matched font assets from a sibling Rafii build. The two legacy social-image glyph requests that required the external network remain visually unverified. No external font fetch is needed to run the backend or SQL tests.

## Database and deployment prerequisites

Migration `migrations/postriff/131_creative_video_projects.sql` belongs after the existing workspace schema. The optional credit-plan path uses Rafii's existing `020_credit_quotes.sql`. Local validation applies both to a disposable database. Production schema migration, secret configuration and a hosted release remain the release owner's separate decisions.

The hosted service needs its existing session verifier, database and private video storage. The existing Library switch is `RAFII_VIDEO_UPLOADS_ENABLED`. A credit-backed workspace needs the existing credit feature, an eligible plan, available balance and its existing workspace and global budget permissions. The project's special internal-workspace or exemption policies retain their existing identity checks. Nothing in the test funding or example media constitutes live spending authorization.

## Model and licensing

The new adapter asks Google Vertex for one 720p take with generated audio. The returned clip is trimmed locally to the scene duration. The estimate rounds up to one of the supported 4-, 6- or 8-second requests. At the adapter's USD 0.10 per generated second estimate, a four-second request estimates USD 0.40. The user's actual pricing, capacity and invoice are unverified. The model documentation identifies fixed quota or provisioned capacity for this route. The worker needs a separately entitled Google Cloud project in the supported region, a short-lived worker OAuth token and a confirmed workspace budget. Model configuration is server-only and the isolated Preview environment disables the route. [Model and quota](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/veo/3-1-generate) · [Official request protocol](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/generate-videos-from-text) · [Pricing](https://cloud.google.com/model-garden/pricing) · [Cloud service-specific terms](https://cloud.google.com/terms/service-terms)

The explicit worker configuration uses `RAFII_CREATIVE_VIDEO_PROVIDER=vertex-veo`, `RAFII_CREATIVE_VIDEO_PROJECT` and `RAFII_CREATIVE_VIDEO_ACCESS_TOKEN`. Supply those through the existing secret owner for an authorized worker. No credential or real customer footage is needed for the production build, the local renders or the automated checks. An uncertain request remains bound to its saved reservation. The operator can use Rafii's existing usage-reconciliation procedure with provider evidence. A zero charge also needs evidence.

The implementation uses Rafii's own Python, TypeScript, PostgreSQL, Library and model transport. It invokes the installed media tools. The example source and pictures are independently authored. Homebrew's tested FFmpeg build enables the GPL codec libx264. Worker binary redistribution and codec patent review depend on the actual deployment. Tesseract code and the upstream fast trained-data distribution declare Apache 2.0. Check the provenance and notices for the installed language pack before bundling it. The reference research covers the separate Hypit and third-party license questions. [FFmpeg legal information](https://ffmpeg.org/legal.html) · [Tesseract code license](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE) · [English trained-data distribution](https://github.com/tesseract-ocr/tessdata_fast/blob/main/LICENSE) · [Reference license register](reference/provenance.md)

## Acceptance by creative format

| Format requested | First-wave evidence | Next evidence needed |
| --- | --- | --- |
| Product demonstration | Fictional timer in motion with known cuts, private Library composition, aligned audio and captioned exports; changing the opening preserves every later frame | Actual product, factual product review, faithful newly generated motion and owner approval |
| Fast-paced social video | Three short scenes and a revised opening in the same diagnostic | A cleared social reference, matched creative brief, original live take and a platform playback check |
| UGC advertisement | Pipeline can accept a rights-confirmed video; no qualified advertisement | Cleared creator, product and reference, actual original output and customer review |
| Talking-head education | No verified speaker identity, speech alignment or full acceptance example | Consented speaker, cleared script, synchronized audio and reviewer evaluation |
| Cinematic brand advertisement | Local color and cut diagnostics only | Cleared cinematic reference, camera-direction review, original footage and brand sign-off |

For each cleared run, preserve the project and source revision, rights scope, proposed strategy, approved facts, generated take identities, measured latency, actual cost or explicit absence, first and revised exports and hashes for unaffected shots. Ask the reviewer to score product accuracy, originality, brand voice, visual quality and strategy fidelity separately. Cost per accepted creative requires both an invoice and an acceptance. A successful render alone establishes neither.
