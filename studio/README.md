# James Au Studio

A standalone local workspace for James's 33-channel content workflow. Phase A stores drafts, platform-native copy, reusable Markdown templates, local images, proposed calendar dates and activity in SQLite. Phase B adds persistent guided drafting and a qualification-gated Codex content bridge. Phase C-local adds exact review and durable scheduling of manual handoff tasks. It does not connect social accounts, schedule remote posts or publish anything.

## Installed use

The installed source/build lives at `/Users/ouxianxing/Documents/James-Au-Studio`. Double-click `Start Studio.command` in that folder to start the local service and open your browser. Application data defaults to `/Users/ouxianxing/Library/Application Support/JamesAuStudio` and is separate from the checkout. The data directory and its files are owner-only. Neither location is a cloud deployment or an always-on service.

```sh
cd /Users/ouxianxing/Documents/James-Au-Studio
.venv/bin/python scripts/studio.py start
.venv/bin/python scripts/studio.py status
.venv/bin/python scripts/studio.py stop
```

Open `http://127.0.0.1:4310`. The launcher refuses to stop a different application occupying this port. If another service already uses it, select a different local `--port` explicitly. Start/stop are manual; no launch-at-login or external publishing worker is installed. A separately supervised local handoff worker runs with the service, independent of browser tabs. It starts paused for a new or restored workspace. The computer and service must be awake for tasks to become due; these are not cloud schedules or mobile push notifications.

The initial document navigation establishes a local HttpOnly session. After restarting the service, reload the page to renew it. No password, API key or social-media credential belongs in this app. The local session and web-origin checks protect against unwanted website requests; they do not establish isolation from arbitrary programs already running as your OS user.

## Working with content

1. Create a draft, retain source notes and your own perspective separately.
2. Choose channels and edit their own native text, language and format. Catalog availability does not imply the platform's current publishing constraints are verified.
3. Select a versioned Markdown template or no template. Guizang's ten themes/28 layouts remain selectable reference vocabulary, not an activated upstream renderer.
4. Add optional local PNG/JPEG/WebP images and accessibility descriptions. These are uploaded only to your loopback app, not to social media.
5. Save. The server assigns a revision; conflicting edits never silently overwrite another saved revision.
6. Add an optional proposed date/time. The calendar records intentions only; no timer or publishing job is created.

Archive is recoverable. Export produces a local Markdown handoff. The original browser-storage prototype is separate and is not silently imported into real drafts.

## Review and local delivery queue

Save the final draft, then prepare a handoff for one selected channel. Enter the
account/destination labels, audience, proposed local time, IANA timezone and
allowed handoff window. Labels are your notes, not verified connections. Additional
Stories/Reels/Shorts require separate native drafts and reviews; this increment
does not append derivatives. Nonexistent DST times are rejected; ambiguous times
require choosing the first or second occurrence.

Review the frozen copy, native format, ordered image hashes/alt text, selected
template version, destination, local/UTC time and manifest hash. Confirmation
queues that exact **local handoff task only**. It does not authorize publication.
Use Delivery to resume or pause the local worker and inspect its heartbeat.

- `queued_local`: saved locally, waiting for its time and an unpaused worker.
- `human_action_needed`: due and eligible for manual-package download.
- `needs_review`: stale content or a missed window; prepare a fresh exact review.
- `cancelled`: local task revoked; this cannot recall anything already posted.
- `user_reported`: you supplied a permalink; Studio has not fetched or independently
  verified it and does not mark the post published.

Editing a bound draft, archiving it, or changing the actual selected media/template
invalidates pending acknowledgment. Simply adding another immutable template
version does not alter the selected old version. After a missed window the worker
does not catch up automatically. Pausing does not cancel or shift approved times.
Remote scheduling and automatic dispatch remain unavailable until exact platform
routes and credentials are independently qualified.

## Account setup preparation

### YouTube read-only identity connection (v0.5.1)

Channels → YouTube binds `jamesaucreates@gmail.com` to channel ID
`UCzwNcXaG4EdjR27Tm9JH_zA`. It requests OpenID email identity plus
`youtube.readonly`, then verifies the email and authenticated
`channels.list(mine=true)` result. Upload, edit, delete, comment and publication
scopes are absent.

Enable YouTube Data API v3 in a Google Cloud project and create a Web OAuth client
with exact redirect URI `http://127.0.0.1:4313/callback`. Store its client ID and
secret in Apple Keychain under service `James Au Studio YouTube OAuth`, accounts
`client-id` and `client-secret`. Studio reads them into the private broker only at
startup. Until both exist, the UI reports `configuration required` and cannot
start consent.

Version 0.5.1 accepts Google's canonical email scope alias, rejects additional
or missing scopes, and validates token expiry. **Check connection** performs a
new email/channel API check for a saved identity and refreshes expired access
inside the broker. Status reads alone make no provider calls. Expiry, broker
restart, revocation, or a failed identity check require fresh verification;
previous evidence is never treated as a current connection. A missing broker
is reported separately from missing client configuration. YouTube startup is
independent of the Bluesky SDK.

### Bluesky identity connection (v0.4.0)

Channels → Bluesky now includes **Connect your Bluesky account**. Create an
account privately if necessary, enter its public handle, review identity-only
access, then choose **Continue to Bluesky**. Complete sign-in/consent in the
provider page. The private broker handles the callback and returns to Studio.
Reopen Channels → Bluesky to inspect the actual identity result.

Only `atproto` identity scope is requested. OAuth subject and an independent
public profile must match the requested handle. Identity connection does not
enable posting, messages, profile edits or scheduling. A separately reviewed
scope change and exact approved tests are required for later publishing.

The official pinned Node OAuth SDK runs in a separate loopback process on the
Studio port + 2 (default 4312). OAuth tokens, state and DPoP keys are encrypted
in the private sibling `JamesAuStudio-Connections` directory, outside Studio
backups and the content agent's filesystem boundary. There is no token-read
API. Logging does not include provider errors or callback queries. If sign-in
is interrupted, wait ten minutes before starting a fresh flow. A broker outage
requires restarting Studio; never paste credentials to work around an error.

After installing/updating broker source, install the pinned dependencies:

```sh
cd /Users/ouxianxing/Documents/James-Au-Studio/studio/broker
npm ci --ignore-scripts --no-audit --no-fund
```

Node 22+ is required. The ordinary launcher starts/stops the private broker with
Studio. Provider/account creation and first real OAuth remain human-dependent;
a passing synthetic callback test is not proof of a connected account.

### Setup candidates for the remaining routes

Open **Channels**, select a channel and choose its native format. Enter public
account and destination labels, then choose **Preview setup plan**. Download the
JSON candidate to keep the exact target, requirements, evidence and fingerprint.
Editing a label clears the old preview. Closing the dialog clears the form;
candidates are not stored as account connections or approval receipts.

Bluesky text and WeChat Channels video are pilot candidates. The current
available route remains manual handoff. Documentation, private connection,
permissions/cost review, exact setup consent and separately approved route tests
must be completed before live delivery. Never enter credentials in these fields.
The Phase D preparation flow makes no provider requests and cannot connect or
publish. Database schema remains 3; no new migration is needed for v0.3.1.

## Guided drafting with Codex

Save a draft with at least one selected channel, language and format, then choose **Start guided drafting**. Existing source/angle are reused. Missing source, your perspective and the intended takeaway are asked one at a time and saved locally. An explicit neutral-summary angle is available; the system does not invent your personal view.

Choose **Review exact input**, inspect the supplied text/template/selected channels, and confirm model usage before pressing **Generate candidate**. No model request occurs while opening Studio, answering questions or checking status. Supplied URLs remain text: this phase does not research the web, verify news or send image bytes. The existing Codex login is used by the official CLI; Studio never asks for or reads raw credentials. Instructions and input are hash-bound, and generation uses a reviewed CLI version/model/isolation policy. An unqualified version or policy makes generation unavailable, not silently less restricted.

Review the resulting canonical brief, warnings and each platform-native candidate. Select which copies to apply to the draft. This is a separate local action, not publication approval. Changed or unsaved drafts cannot be overwritten by stale output. You can edit the applied copy and start a fresh conversation from the new revision. Prior conversations and runs remain inspectable.

One generation can run per workspace. Cancel/Check controls remain available when another draft is selected. Closing the browser does not cancel a run; stopping the service interrupts it without automatic retry. Fixed duration/output limits stop runaway requests; reported token usage is shown when available, but is not a promised monetary cost ceiling. Copy-to-Codex remains a separate manual fallback with no automatic Studio write authority.

Studio never automatically starts a second generation job. The official CLI may internally reconnect/retry within the same 180-second tracked invocation; this is not a guarantee of one HTTP attempt or zero retry-related model usage. The supported built-in OpenAI provider does not expose a documented zero-retry override. Studio does not replace that provider or alter login/endpoint behavior to claim otherwise.

## Backup and safe restore

Download a backup in the app, or choose a new output file through the CLI:

```sh
.venv/bin/python scripts/studio.py backup --output /private/tmp/james-au-studio-backup.zip
.venv/bin/python scripts/studio.py restore --archive /private/tmp/james-au-studio-backup.zip --target /private/tmp/james-au-studio-restored
```

Backup uses SQLite's backup API and includes an asset integrity manifest. Keep this file private: it contains your content, images, guided conversation/run history and local delivery reviews/receipts. No provider credentials, service session values, raw reasoning or browser profiles are included. Schema-1/2 backups migrate to schema 3; unfinished agent runs become interrupted on restore and never resume automatically. Restored delivery is paused, active leases are cleared and pending tasks require fresh review; manual reports remain unverified.

Restore requires a new destination path and refuses all existing destinations, unsafe archive paths, invalid schema/bounds or hash mismatches. It does not overwrite the currently running workspace. To inspect a restored workspace, stop the original service and start with `--data-dir <restored-directory>`, or choose another port. Restore does not enable delivery.

## Development and tests

From the source checkout:

```sh
python3 -m venv .studio-venv
.studio-venv/bin/python -m pip install -r studio/requirements.lock.txt
cd studio/web
npm ci --ignore-scripts
npm run build
cd ../..
.studio-venv/bin/python scripts/studio.py start --data-dir /private/tmp/studio-development --port 4311
env PYTHONPATH=src .studio-venv/bin/python -m unittest discover -s tests
python3 scripts/verify_project.py
```

Use `studio/requirements.txt` if constructing a new reviewed dependency lock; the release uses exact transitive versions in the lock. The npm lock pins the frontend; no remote CSS, font or animation CDN is required at runtime.

The installer is source-allowlisted and checksum-verifies the copy:

```sh
python3 scripts/install_studio.py --destination /Users/ouxianxing/Documents/James-Au-Studio --with-env
```

It preserves unrelated destinations, refuses modified managed files on update, excludes `.git`, `.env`, browser state, runtime databases, caches and `node_modules`, and never moves or deletes the source checkout.

## Remaining phases

Phase C's local/manual path is available; its remote submission/lock/reconciliation
path remains gated along with live account/API/browser qualification. RSS/research
execution, visual/video rendering and metrics follow separately. All connected/
publish-ready counts remain zero until each account and operation has genuine
evidence. This workspace is not the complete V14/V15 production engine. Existing
V14 synthetic publishing tests are not real Studio transport tests.
