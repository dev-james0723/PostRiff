import { useEffect, useState } from "react";
import type { Access, AlphaState, Snapshot } from "./types";
import type { Asset, Job } from "./phase2-types";
import { ACCESS_KEY, api, readLocal } from "./api";
import "./phase2.css";
type Props = {
  state: AlphaState;
  busy: boolean;
  act: (
    a: string,
    p?: Record<string, unknown>,
  ) => Promise<Snapshot | undefined>;
};
const stamp = (n: number) => new Date(n * 1000).toLocaleString();
const fixture = (
  <span className="p2-fixture">LOCAL FIXTURE · NO EXTERNAL ACTION</span>
);
function Header({ title, children, execution }: { title: string; children: string; execution?: string }) {
  return (
    <header className="section-heading">
      <div className="eyebrow">YOUR AGENCY / PHASE 2</div>
      <h1 id="main-title" tabIndex={-1}>
        {title}
      </h1>
      <p className="lede">{children}</p>
      {execution === "hosted-candidate" ? (
        <span className="p2-fixture">HOSTED CANDIDATE · PROVIDERS FAIL CLOSED</span>
      ) : fixture}
    </header>
  );
}

function MediaPreview({ asset }: { asset: Asset }) {
  const [url, setUrl] = useState(
    asset.data ? `data:${asset.mime};base64,${asset.data}` : "",
  );
  useEffect(() => {
    if (asset.data) return;
    let active = true,
      objectUrl = "";
    const access = readLocal<Access | null>(ACCESS_KEY, null);
    if (access)
      void api
        .media(access, asset.id)
        .then((blob) => {
          if (active) {
            objectUrl = URL.createObjectURL(blob);
            setUrl(objectUrl);
          }
        })
        .catch(() => setUrl(""));
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [asset.id, asset.data, asset.mime]);
  return url ? (
    <img className="p2-media" alt="Selected post image" src={url} />
  ) : (
    <p className="helper">Loading private image preview…</p>
  );
}

export function Channels({ state, busy, act }: Props) {
  const [scenario, setScenario] = useState("success");
  const p = state.phase2!;
  return (
    <>
      <Header title="Channels" execution={p.execution}>
        Know which account is ready, and exactly what it can do.
      </Header>
      <div className="p2-channel-grid">
        {["LinkedIn", "Instagram"].map((platform) => (
          <article className="p2-card" key={platform}>
            <div className="p2-platform">
              {platform === "LinkedIn" ? "in" : "◎"}
            </div>
            <h2>{platform}</h2>
            <p>
              {platform === "LinkedIn"
                ? "Member posts · text and one image"
                : "Professional accounts · single image posts"}
            </p>
            <p className="helper">{p.execution === "hosted-candidate" ? "Provider OAuth and capability verification must be configured before this account can be added." : "Live configuration unavailable. Test the account contract with a fictional destination."}</p>
            <button
              className="button secondary"
              disabled={busy || p.execution === "hosted-candidate"}
              onClick={() => void act("p2_channel_add", { platform })}
            >
              {p.execution === "hosted-candidate" ? `${platform} setup pending` : `Add ${platform} fixture →`}
            </button>
          </article>
        ))}
      </div>
      <p className="helper">
        Threads and other destinations: continue using native drafts and export.
      </p>
      {p.execution !== "hosted-candidate" && <label className="field narrow">
        Fixture verification outcome
        <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
          {[
            "success",
            "denied",
            "expired",
            "accepted",
            "delayed",
            "failed",
            "rate_limited",
            "timeout",
            "duplicate",
            "uncertain",
            "malformed",
            "capability_loss",
          ].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>}
      <div className="p2-stack">
        {p.channels.map((c) => (
          <article className="p2-card" key={c.id}>
            <div className="p2-row">
              <div>
                <span className="eyebrow">
                  {c.evidenceSource === "live_provider" ? "VERIFIED" : "SYNTHETIC"} {c.platform.toUpperCase()}
                </span>
                <h2>{c.account}</h2>
              </div>
              <span
                className={`p2-status ${c.displayState === "Ready for posting" ? "verified" : "held"}`}
              >
                {c.displayState} · {c.evidenceSource === "live_provider" ? "provider" : "fixture"}
              </span>
            </div>
            <p>
              {c.accountType} · {c.language} · {c.evidenceSource === "live_provider" ? "server verified" : "implemented with fixtures"}
            </p>
            <dl className="p2-facts">
              <div>
                <dt>Identity</dt>
                <dd>
                  {c.identityVerified ? (c.evidenceSource === "live_provider" ? "Provider verified" : "Synthetic verification") : "Unverified"}
                </dd>
              </div>
              <div>
                <dt>Capability</dt>
                <dd>
                  {c.capabilityVerified
                    ? `${c.evidenceSource === "live_provider" ? "Provider" : "Fixture"} version ${c.capabilityVersion}`
                    : "Unverified"}
                </dd>
              </div>
              <div>
                <dt>Last checked</dt>
                <dd>{c.verifiedAt ? stamp(c.verifiedAt) : "Not checked"}</dd>
              </div>
            </dl>
            <details>
              <summary>Permission and evidence details</summary>
              <p>
                {c.scopes.join(", ") || "No granted scopes"} · evidence:{" "}
                {c.evidenceSource} · expiry: {stamp(c.expiresAt)}
              </p>
              {c.evidenceSource !== "live_provider" && <p>No provider app, token or real account identity has been verified.</p>}
            </details>
            <div className="button-row">
              <button
                className="button"
                disabled={busy || c.evidenceSource === "live_provider"}
                onClick={() =>
                  void act("p2_channel_verify", { channelId: c.id, scenario })
                }
              >
                {c.evidenceSource === "live_provider" ? "Capability verified" : "Verify fixture capability"}
              </button>
              <button
                className="text-button danger"
                disabled={busy}
                onClick={() =>
                  void act("p2_channel_disconnect", { channelId: c.id })
                }
              >
                Disconnect {c.evidenceSource === "live_provider" ? "channel" : "fixture"}
              </button>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

function Receipt({
  job,
  busy,
  act,
}: { job: Job } & Pick<Props, "act" | "busy">) {
  return (
    <article className="p2-card p2-job">
      <div className="p2-row">
        <span className={`p2-status ${job.state}`}>
          {job.state.replaceAll("_", " ")} · {job.manifest.execution === "hosted-live" ? "provider" : "synthetic"}
        </span>
        <small>Revision {job.manifest.contentRevision}</small>
      </div>
      <h3>{job.manifest.account}</h3>
      <p className="p2-excerpt">{job.manifest.payload.text}</p>
      <p className="helper">
        {job.manifest.timing.local} · {job.manifest.timing.timeZone}
        <br />
        UTC: {job.manifest.timing.utc}
      </p>
      <p>{job.providerConfirmed || (job.manifest.execution === "hosted-live" ? "Waiting for the hosted worker." : "Waiting for the local worker.")}</p>
      <details>
        <summary>Destination receipt & approval</summary>
        <dl>
          <dt>Intended action</dt>
          <dd>{job.manifest.operation}</dd>
          <dt>Attempts</dt>
          <dd>{job.attempts.length}</dd>
          <dt>Provider correlation</dt>
          <dd>{job.providerReference || "None"}</dd>
          <dt>Verification</dt>
          <dd>
            {job.verification
              ? `${job.verification.method} · ${stamp(job.verification.at)}`
              : "Not verified"}
          </dd>
        </dl>
        <ol className="p2-events">
          {job.events.map((e, i) => (
            <li key={i}>
              <time>{stamp(e.at)}</time>
              <strong>{e.state}</strong>
              <span>{e.message}</span>
            </li>
          ))}
        </ol>
        <pre>{JSON.stringify(job.manifest, null, 2)}</pre>
      </details>
      <p className="helper">
        {job.nextAction || "Review or cancel before the worker submits."}
        {job.cancelRequested &&
          " Cancellation requested; submitted outcomes still require reconciliation."}
      </p>
      {!["canceled", "failed", "verified"].includes(job.state) && (
        <button
          className="text-button danger"
          disabled={busy || job.cancelRequested}
          onClick={() => void act("p2_cancel", { jobId: job.id })}
        >
          Cancel this destination
        </button>
      )}
    </article>
  );
}

export function Scheduling({
  state,
  busy,
  act,
  reload,
}: Props & { reload: () => Promise<void> }) {
  const p = state.phase2!;
  const [variantId, setVariant] = useState(""),
    [channelId, setChannel] = useState(""),
    [assetId, setAsset] = useState(""),
    [alt, setAlt] = useState(""),
    [rights, setRights] = useState(false),
    [ack, setAck] = useState(false),
    [excluded, setExcluded] = useState(false),
    [view, setView] = useState("List"),
    [time, setTime] = useState(""),
    [zone, setZone] = useState(
      () => Intl.DateTimeFormat().resolvedOptions().timeZone,
    ),
    [fold, setFold] = useState(""),
    [error, setError] = useState("");
  const v = state.variants.find((v) => v.id === variantId);
  const [reviewId, setReview] = useState<string | null>(null);
  const review = p.reviews.find((r) => r.id === reviewId);
  useEffect(() => {
    const timer = setInterval(() => {
      if (!busy) void reload();
    }, 5000);
    return () => clearInterval(timer);
  }, [busy, reload]);
  const changed = () => setReview(null);
  async function upload(file: File) {
    try {
      setError("");
      if (file.size > 8 * 1024 * 1024)
        throw Error("Choose an image up to 8 MB.");
      const bytes = new Uint8Array(await file.arrayBuffer());
      let text = "";
      for (let i = 0; i < bytes.length; i += 16384)
        text += String.fromCharCode(...bytes.subarray(i, i + 16384));
      await act("p2_media_upload", { data: btoa(text) });
    } catch (e) {
      setError(String(e));
    }
  }
  async function prepare() {
    if (!v) return;
    const r = await act("p2_review", {
      variantId,
      channelId,
      assetId: assetId || undefined,
      alt,
      rightsConfirmed: rights,
      localTime: time,
      timeZone: zone,
      fold: fold === "" ? undefined : Number(fold),
      acknowledgedWarnings: ack ? v.warnings : [],
    });
    if (r) setReview(r.state.phase2!.reviews.at(-1)!.id);
  }
  const jobs = [...p.jobs].sort((a, b) =>
    a.manifest.timing.utc.localeCompare(b.manifest.timing.utc),
  );
  return (
    <>
      <Header title="Scheduling" execution={p.execution}>
        Review each destination. Keep every outcome visible.
      </Header>
      <section className="p2-card">
        <h2>Prepare a destination</h2>
        <p className="helper">
          {p.execution === "hosted-candidate" ? "The hosted worker stays fail closed until a server-verified channel is present. Each destination gets its own approval and receipt." : "All submissions on this runtime go to local fixtures. Each destination gets its own approval and receipt."}
        </p>
        {error && <p role="alert">{error}</p>}
        <div className="p2-form-grid">
          <label className="field">
            Draft variant
            <select
              value={variantId}
              onChange={(e) => {
                setVariant(e.target.value);
                setAck(false);
                setExcluded(false);
                changed();
              }}
            >
              <option value="">Choose a draft</option>
              {state.variants.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.platform} · {v.language} · revision {v.revision}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Exact destination account
            <select
              value={channelId}
              onChange={(e) => {
                setChannel(e.target.value);
                changed();
              }}
            >
              <option value="">Choose an exact account</option>
              {p.channels.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.account} · {c.displayState}
                </option>
              ))}
            </select>
          </label>
        </div>
        {!state.variants.length && <p>Create a draft in Ideas first.</p>}
        {v && (
          <>
            <blockquote className="p2-draft">{v.text}</blockquote>
            {(v.needsReview || v.unknowns.length > 0) && (
              <div className="p2-review-warning">
                <h3>Review the draft first</h3>
                <ul>
                  {v.unknowns.map((u, i) => (
                    <li key={i}>{u}</li>
                  ))}
                </ul>
                <label className="scope-check">
                  <input
                    type="checkbox"
                    checked={excluded}
                    onChange={(e) => setExcluded(e.target.checked)}
                  />
                  I read this revision, checked its sources, and confirmed
                  unsupported details above are excluded from the draft.
                </label>
                <button
                  className="button secondary"
                  disabled={busy || !excluded}
                  onClick={() =>
                    void act("p2_variant_review", {
                      variantId: v.id,
                      variantRevision: v.revision,
                      confirmed: true,
                      excludedUnknowns: v.unknowns,
                    })
                  }
                >
                  Record my draft review
                </button>
                <p className="helper">
                  Edit in Ideas first if it still makes an unsupported claim.
                  This records your review; it does not verify a fact.
                </p>
              </div>
            )}
            {v.warnings.length > 0 && (
              <>
                <ul>
                  {v.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
                <label className="scope-check">
                  <input
                    type="checkbox"
                    checked={ack}
                    onChange={(e) => {
                      setAck(e.target.checked);
                      changed();
                    }}
                  />
                  I acknowledge these warnings.
                </label>
              </>
            )}
          </>
        )}
        <details>
          <summary>Image, alt text & rights</summary>
          <label className="field">
            Upload JPEG or PNG (8 MB maximum)
            <input
              type="file"
              accept="image/jpeg,image/png"
              disabled={busy}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void upload(f);
                changed();
              }}
            />
          </label>
          <label className="field">
            Decoded image
            <select
              value={assetId}
              onChange={(e) => {
                setAsset(e.target.value);
                changed();
              }}
            >
              <option value="">No image</option>
              {p.assets
                .filter((a) => !a.deleted)
                .map((a, i) => (
                  <option key={a.id} value={a.id}>
                    Image {i + 1} · {a.width} × {a.height} · JPEG
                  </option>
                ))}
            </select>
          </label>
          {assetId && (
            <>
              {p.assets.find((asset) => asset.id === assetId) && (
                <MediaPreview
                  asset={p.assets.find((asset) => asset.id === assetId)!}
                />
              )}
              <label className="field">
                Alt text
                <textarea
                  maxLength={1000}
                  value={alt}
                  onChange={(e) => {
                    setAlt(e.target.value);
                    changed();
                  }}
                />
              </label>
              <label className="scope-check">
                <input
                  type="checkbox"
                  checked={rights}
                  onChange={(e) => {
                    setRights(e.target.checked);
                    changed();
                  }}
                />
                I have the rights to publish this image.
              </label>
              <button
                className="text-button danger"
                disabled={busy}
                onClick={() =>
                  void act("p2_media_delete", { assetId }).then((r) => {
                    if (r) setAsset("");
                  })
                }
              >
                Delete image
              </button>
            </>
          )}
        </details>
        <div className="p2-form-grid">
          <label className="field">
            Local date and time
            <input
              type="datetime-local"
              value={time}
              onChange={(e) => {
                setTime(e.target.value);
                changed();
              }}
            />
          </label>
          <label className="field">
            IANA time zone
            <input
              value={zone}
              onChange={(e) => {
                setZone(e.target.value);
                changed();
              }}
              placeholder="America/Indiana/Indianapolis"
            />
          </label>
          <label className="field">
            If clocks repeat this time
            <select
              value={fold}
              onChange={(e) => {
                setFold(e.target.value);
                changed();
              }}
            >
              <option value="">Ask me if ambiguous</option>
              <option value="0">First occurrence</option>
              <option value="1">Second occurrence</option>
            </select>
          </label>
        </div>
        <button
          className="text-button"
          onClick={() => {
            try {
              setTime(
                new Intl.DateTimeFormat("sv-SE", {
                  timeZone: zone,
                  year: "numeric",
                  month: "2-digit",
                  day: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                  hourCycle: "h23",
                })
                  .format(new Date(Date.now() + 120000))
                  .replace(" ", "T"),
              );
              changed();
            } catch {
              setError("Enter a valid IANA time zone first.");
            }
          }}
        >
          Set two minutes from now
        </button>
        <button
          className="button"
          disabled={busy || !variantId || !channelId || !time}
          onClick={() => void prepare()}
        >
          Run preflight & review →
        </button>
      </section>
      {review && (
        <section className="p2-card p2-exact-review">
          <span className="eyebrow">EXACT DESTINATION APPROVAL</span>
          <h2>{review.manifest.account}</h2>
          <blockquote className="p2-draft">
            {review.manifest.payload.text}
          </blockquote>
          <p>
            {review.manifest.operation} · draft revision{" "}
            {review.manifest.contentRevision}
            <br />
            {review.manifest.timing.local} · {review.manifest.timing.timeZone}
            <br />
            Resolved UTC: {review.manifest.timing.utc}
          </p>
          <p>
            {review.manifest.media.length} image(s) ·{" "}
            {review.manifest.media.map((m) => m.alt).join(" · ")}
          </p>
          <details>
            <summary>Inspect the immutable manifest</summary>
            <pre>{JSON.stringify(review.manifest, null, 2)}</pre>
            <p className="helper">Digest: {review.digest}</p>
          </details>
          <p className="helper">
            Content, account, media, voice, capability or timing changes require
            a new review. Status: {review.status}
          </p>
          <button
            className="button"
            disabled={busy || review.status !== "needs_review"}
            onClick={() =>
              void act("p2_approve", {
                reviewId: review.id,
                digest: review.digest,
                confirmed: true,
              })
            }
          >
            Approve & schedule this {review.manifest.execution === "hosted-live" ? "provider" : "fixture"} destination
          </button>
        </section>
      )}
      <div className="p2-row p2-schedule-heading">
        <div>
          <h2>Your destination jobs</h2>
          <p>
            {jobs.length} independent receipt{jobs.length === 1 ? "" : "s"} · no
            real posts published
          </p>
        </div>
        <div className="button-row" role="group" aria-label="Schedule view">
          {["List", "Calendar", "Kanban"].map((name) => (
            <button
              className="button secondary"
              key={name}
              aria-pressed={view === name}
              onClick={() => setView(name)}
            >
              {name}
            </button>
          ))}
        </div>
      </div>
      {jobs.length === 0 ? (
        <div className="p2-empty">
          <span>▦</span>
          <h3>Space for your next idea.</h3>
          <p>Approved fixture destinations will appear here.</p>
        </div>
      ) : view === "List" ? (
        <div className="p2-stack">
          {jobs.map((job) => (
            <Receipt key={job.id} job={job} busy={busy} act={act} />
          ))}
        </div>
      ) : (
        <div
          className={`p2-grouped ${view === "Calendar" ? "p2-calendar" : ""}`}
        >
          {[
            ...new Set(
              jobs.map((j) =>
                view === "Calendar"
                  ? j.manifest.timing.local.slice(0, 10)
                  : j.state,
              ),
            ),
          ].map((group) => (
            <section key={group}>
              <h3>{group.replaceAll("_", " ")}</h3>
              {jobs
                .filter(
                  (j) =>
                    (view === "Calendar"
                      ? j.manifest.timing.local.slice(0, 10)
                      : j.state) === group,
                )
                .map((job) => (
                  <Receipt key={job.id} job={job} busy={busy} act={act} />
                ))}
            </section>
          ))}
        </div>
      )}
    </>
  );
}

export function Artwork({ state, busy, act }: Props) {
  const p = state.phase2!,
    art = p.art;
  const [consent, setConsent] = useState(false),
    [count, setCount] = useState(3),
    [focal, setFocal] = useState(50);
  return (
    <section className="p2-card">
      <span className="eyebrow">A VISUAL INTERPRETATION OF YOUR VOICE</span>
      <h2>Choose your watercolor</h2>
      <p>
        Inspired by choices you approved. Preview and select an interpretation
        to keep with your profile.
      </p>
      {fixture}
      <p>
        One onboarding set · up to 3 previews · local cost $0 · no image
        provider request.
      </p>
      {art.providerBrief ? (
        <>
          <details open>
            <summary>Exact provider-bound ArtBrief</summary>
            <pre>{JSON.stringify(art.providerBrief, null, 2)}</pre>
          </details>
          <p className="helper">
            Use the field checkboxes above to remove a source. Internal profile
            and source IDs stay in the workspace.
          </p>
          <label className="scope-check">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            I approve this brief for a local fixture preview set. No paid or
            live generation is authorized.
          </label>
          <label className="field narrow">
            Preview count
            <select
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
            >
              {[1, 2, 3].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <div className="button-row">
            <button
              className="button"
              disabled={busy || !consent}
              onClick={() =>
                void act("p2_art_generate", {
                  consent: true,
                  briefHash: art.briefHash,
                  count,
                })
              }
            >
              Create local previews
            </button>
            <button
              className="text-button"
              disabled={busy}
              onClick={() => void act("p2_art_generate", { consent: false })}
            >
              Keep the local fallback
            </button>
          </div>
        </>
      ) : (
        <p>
          Select approved public fields with two abstract themes, such as warm
          and clear, in the ArtBrief controls above. The local fallback is
          available meanwhile.
        </p>
      )}
      <p role="status">
        {art.status.replaceAll("_", " ")} · {p.trial.artworkUsed}/1 onboarding
        set used
      </p>
      <div className="p2-art-grid">
        {art.candidates.map((a, i) => (
          <article key={a.id}>
            <img
              src={`data:${a.mime};base64,${a.data}`}
              alt={`Procedural watercolor fixture ${i + 1}`}
            />
            <button
              className="button secondary"
              disabled={busy}
              onClick={() =>
                void act("p2_art_select", {
                  assetId: a.id,
                  focal: [focal / 100, 0.5],
                })
              }
            >
              {art.selected?.id === a.id ? "Selected" : "Choose"} preview{" "}
              {i + 1}
            </button>
          </article>
        ))}
      </div>
      {art.candidates.length > 0 && (
        <label className="field">
          Horizontal focal point
          <input
            type="range"
            min={0}
            max={100}
            value={focal}
            onChange={(e) => setFocal(Number(e.target.value))}
          />
          {focal}% · applied when you select a preview
        </label>
      )}
      {art.selected && (
        <a
          className="button secondary"
          download="postriff-selected-watercolor.svg"
          href={`data:${art.selected.mime};base64,${art.selected.data}`}
        >
          Download selected artwork
        </a>
      )}
      <button
        className="text-button danger"
        disabled={busy}
        onClick={() => void act("p2_art_delete")}
      >
        Delete this set and selection
      </button>
      <p className="helper">
        Profile changes never replace your selection. Deletion removes stored
        image bytes; consent metadata stays in your private export. Further paid
        regeneration is unavailable.
      </p>
    </section>
  );
}

export function Plan({ state, busy, act }: Props) {
  const t = state.phase2!.trial;
  return (
    <>
      <h2>Your trial, clearly accounted for.</h2>
      {fixture}
      <p>
        14 days · no card · no automatic conversion. Every available plan
        includes all released skills and all four agency modes.
      </p>
      <div className="p2-channel-grid">
        {[
          ["studio", "Studio", 19],
          ["assist", "Assist", 39],
        ].map(([id, name, price]) => (
          <article className="p2-card" key={id}>
            <h3>{name}</h3>
            <strong>
              ${price}/month <small>candidate price</small>
            </strong>
            <p>
              {id === "assist"
                ? "Drafts, export, scheduling and assisted-writing contracts"
                : "Drafts, export and scheduling contracts"}
            </p>
            <button
              className="button secondary"
              disabled={busy || t.plan === id}
              onClick={() => void act("p2_plan", { plan: id })}
            >
              {t.plan === id ? "Selected trial" : "Switch trial plan"}
            </button>
          </article>
        ))}
      </div>
      <div className="usage-grid">
        <section>
          <span>Shared writing simulation</span>
          <strong>
            {t.writingUsed} / {t.writingGrant}
          </strong>
          <p>
            One nonrenewing grant across plan switches. No real model usage.
          </p>
        </section>
        <section>
          <span>Trial status</span>
          <strong>{t.status}</strong>
          <p>
            Ends {stamp(t.expiresAt)}. Expiry preserves export and holds future
            jobs.
          </p>
        </section>
      </div>
      <p>
        Business $79: unavailable. Billing, charges, live usage metering and
        conversion are outside this release.
      </p>
    </>
  );
}

export function Privacy({
  state,
  busy,
  act,
  signOut,
  exportPack,
  hosted = false,
  deleteHostedAccount,
}: Props & {
  signOut: () => void;
  exportPack: () => Promise<void>;
  hosted?: boolean;
  deleteHostedAccount?: (confirmation: string) => Promise<void>;
}) {
  const [confirmation, setConfirmation] = useState(""),
    [linkError, setLinkError] = useState("");
  const p = state.phase2!;
  async function link() {
    try {
      setLinkError("");
      const principal = readLocal<string>(
        "postriff-alpha-preview-principal",
        "",
      );
      const input = {
        provider: "email",
        principalKey: principal,
        verifier: crypto.randomUUID() + crypto.randomUUID(),
        requestId: crypto.randomUUID(),
        proof: "123456",
      };
      const challenge = await api.challenge(input);
      await act("p2_link_identity", { ...input, state: challenge.state });
    } catch (e) {
      setLinkError(String(e));
    }
  }
  if (hosted)
    return (
      <section className="p2-card">
        <h2>Account & privacy controls</h2>
        <span className="p2-fixture">HOSTED CANDIDATE · SUPABASE SESSION</span>
        <p>
          Your identity is verified by the configured Supabase project.
          Workspace access is checked against active membership on every
          request.
        </p>
        <h3>Private data</h3>
        <p>
          Draft state is stored in PostgreSQL. Uploaded images are decoded by
          the server and stored as immutable objects in a private bucket;
          exports contain metadata and drafts, without access tokens or provider
          credentials.
        </p>
        <div className="button-row">
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => void exportPack()}
          >
            Export private account data
          </button>
          <button
            className="button secondary"
            disabled={busy}
            onClick={signOut}
          >
            Sign out of this browser
          </button>
        </div>
        <p className="helper">
          Signing out revokes this exact hosted session before browser storage
          is cleared. Recovery and social-account permissions remain separate.
        </p>
        <details>
          <summary>Delete this hosted account</summary>
          <p>
            This removes the private workspace, stored media, drafts, jobs and
            Supabase identity. A minimal trial tombstone prevents a second free
            trial. Submitted or uncertain provider outcomes must be reconciled
            first.
          </p>
          <label className="field narrow">
            Type DELETE
            <input value={confirmation} onChange={(e) => setConfirmation(e.target.value)} />
          </label>
          <button
            className="button danger"
            disabled={busy || confirmation !== "DELETE" || !deleteHostedAccount}
            onClick={() => void deleteHostedAccount?.(confirmation).catch((error) => setLinkError(String(error)))}
          >
            Delete hosted account
          </button>
          {linkError && <p role="alert">{linkError}</p>}
        </details>
      </section>
    );
  return (
    <section className="p2-card">
      <h2>Account & privacy controls</h2>
      {fixture}
      <p>
        Signed in with a synthetic local identity. Google and email recovery
        contracts are testable; Apple, Microsoft and phone await provider
        configuration.
      </p>
      {linkError && <p role="alert">{linkError}</p>}
      <h3>Recovery methods</h3>
      <ul>
        {p.identities.map((id) => (
          <li key={id}>
            {id} · fixture{" "}
            <button
              className="text-button"
              disabled={busy || p.identities.length < 2}
              onClick={() => void act("p2_unlink_identity", { provider: id })}
            >
              Unlink
            </button>
          </li>
        ))}
      </ul>
      {!p.identities.includes("email") && (
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => void link()}
        >
          Verify & link email fixture
        </button>
      )}
      <p className="helper">
        The final recovery method cannot be removed. An identity belonging to
        another account cannot merge workspaces.
      </p>
      <h3>Device sessions</h3>
      <ul>
        {p.devices.map((d, i) => (
          <li key={d.id}>
            Session {i + 1} · {d.status} · expires {stamp(d.expiresAt)}{" "}
            <button
              className="text-button"
              disabled={busy || d.status === "revoked"}
              onClick={() => void act("p2_revoke_device", { deviceId: d.id })}
            >
              Revoke
            </button>
          </li>
        ))}
      </ul>
      <div className="button-row">
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => void exportPack()}
        >
          Export private account data
        </button>
        <button
          className="button secondary"
          disabled={busy}
          onClick={() =>
            void act("p2_logout").then((r) => {
              if (r) signOut();
            })
          }
        >
          Sign out & revoke this session
        </button>
      </div>
      <details>
        <summary>Delete this local fixture account</summary>
        <p>
          This removes its private workspace, media, drafts and jobs. A minimal
          deleted-account/trial tombstone prevents recovery from creating
          another trial. Submitted outcomes must be reconciled first.
        </p>
        <label className="field narrow">
          Type DELETE
          <input
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
          />
        </label>
        <button
          className="button danger"
          disabled={busy || confirmation !== "DELETE"}
          onClick={() =>
            void act("p2_delete_account", { confirmation }).then((r) => {
              if (r) signOut();
            })
          }
        >
          Delete local account
        </button>
      </details>
    </section>
  );
}
