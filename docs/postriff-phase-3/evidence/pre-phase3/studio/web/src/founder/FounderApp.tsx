import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import AuthEntry from "./AuthEntry";
import ContentTypes from "./ContentTypes";
import { Channels, Scheduling, Privacy } from "./Phase2";
import YouProfile from "./YouProfile";
import AgentOnboarding from "./AgentOnboarding";
import { ACCESS_KEY, ApiError, api, readLocal, writeLocal } from "./api";
import {
  hostedSession,
  selectedHostedPlan,
  signOutHosted,
} from "./hosted-auth";
import type {
  Access,
  AlphaState,
  Language,
  Mode,
  Platform,
  Profile,
  ProfileMetadata,
  Snapshot,
  Source,
  Template,
  Tone,
  Variant,
} from "./types";

const NAV = [
  "Dashboard",
  "Ideas",
  "Scheduling",
  "Channels",
  "Analytics",
  "Audience",
];
const STEPS = [
  "Your agency",
  "Your AI",
  "Your profile",
  "First PostRiff",
  "Review and save",
];
const MODES: { id: Mode; name: string; description: string; mark: string }[] = [
  {
    id: "personal",
    name: "My personal brand",
    description: "Share my experience, expertise, and point of view.",
    mark: "01",
  },
  {
    id: "niche",
    name: "A niche or expertise",
    description: "Build a focused channel around a subject.",
    mark: "02",
  },
  {
    id: "business",
    name: "My business",
    description: "Create content from my company’s knowledge and offers.",
    mark: "03",
  },
  {
    id: "hybrid",
    name: "A mix of these",
    description: "Combine my voice, a niche, and/or a business.",
    mark: "04",
  },
];
type Act = (
  action: string,
  payload?: Record<string, unknown>,
) => Promise<Snapshot | undefined>;
type FormFields = Record<string, string | string[]>;

function useDraft<T>(id: string, initial: T) {
  const key = `postriff-alpha-draft:${id}`;
  const [value, setValue] = useState<T>(() => readLocal(key, initial));
  function update(next: T) {
    setValue(next);
    try {
      writeLocal(key, next);
    } catch {
      /* Server confirmation still works if browser storage is full. */
    }
  }
  return [value, update] as const;
}
function Button({
  children,
  secondary = false,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { secondary?: boolean }) {
  return (
    <button
      type="button"
      {...props}
      className={`${secondary ? "button secondary" : "button"} ${props.className || ""}`}
    >
      {children}
    </button>
  );
}
function Heading({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <header className="section-heading">
      <div className="eyebrow">{eyebrow}</div>
      <h1 id="main-title" tabIndex={-1}>
        {title}
      </h1>
      {children && <p className="lede">{children}</p>}
    </header>
  );
}
function Tag({ children }: { children: ReactNode }) {
  return <span className="tag">{children}</span>;
}
function BackNext({
  back,
  label = "Continue",
  busy = false,
}: {
  back?: () => void;
  label?: string;
  busy?: boolean;
}) {
  return (
    <div className="form-actions">
      {back && (
        <Button type="button" secondary onClick={back} disabled={busy}>
          ← Back
        </Button>
      )}
      <Button type="submit" disabled={busy}>
        {label}
        <span aria-hidden="true">↗</span>
      </Button>
    </div>
  );
}
function ProfileCard({
  profile,
  title = "Your voice",
}: {
  profile: Profile;
  title?: string;
}) {
  return (
    <section className="profile-card">
      <div className="eyebrow">Provisional · yours to change</div>
      <h2>{title}</h2>
      <ul>
        {profile.observations.map((v, i) => (
          <li key={i}>{v}</li>
        ))}
      </ul>
      <div className="quiet-divider" />
      <h3>Still unknown</h3>
      <ul className="muted">
        {profile.unknowns.map((v, i) => (
          <li key={i}>{v}</li>
        ))}
      </ul>
    </section>
  );
}

export default function FounderApp() {
  const [access, setAccess] = useState<Access | null>(() =>
    readLocal(ACCESS_KEY, null),
  );
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [profileMetadata, setProfileMetadata] =
    useState<ProfileMetadata | null>(null);
  const [nav, setNav] = useState("Ideas");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState("");
  const [menu, setMenu] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const [phase2, setPhase2] = useState(false);
  const [authMode, setAuthMode] = useState<"local" | "supabase">("local");
  const [downloads, setDownloads] = useState(0);
  const [reviewField, setReviewField] = useState<string | null>(null);
  const state = snapshot?.state;
  const step = state?.session.step;
  const chapter =
    step === 0
      ? 0
      : step === 1
        ? ["relationship", "transfer", "scope", "handoff"].includes(
            state?.profileSetup.stage || "",
          )
          ? 1
          : 2
        : step === 3
          ? 2
          : step === 6
            ? 4
            : 3;
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const c = await api.catalog();
        const mode = c.authMode === "supabase" ? "supabase" : "local";
        if (active) {
          setTemplates(c.templates);
          setProfileMetadata(c.profileMetadata);
          setPhase2(Boolean(c.phase2));
          setAuthMode(mode);
        }
        let current = access;
        if (mode === "supabase") {
          const session = await hostedSession();
          if (session && !current) {
            const created = await api.verifyHosted(
              selectedHostedPlan(),
              session.access_token,
            );
            current = {
              workspaceId: created.workspaceId,
              token: session.access_token,
              authMode: "supabase",
            };
            writeLocal(ACCESS_KEY, current);
            writeLocal("postriff-alpha-personal-access", current);
            if (active) {
              setAccess(current);
              setSnapshot(created);
              setNav(created.state.session.completed ? "Dashboard" : "Ideas");
            }
          } else if (!session && current?.authMode === "supabase") {
            localStorage.removeItem(ACCESS_KEY);
            localStorage.removeItem("postriff-alpha-personal-access");
            current = null;
            if (active) setAccess(null);
          }
        }
        if (current) {
          const saved = await api.get(current);
          if (active) {
            setSnapshot(saved);
            setNav(saved.state.session.completed ? "Dashboard" : "Ideas");
          }
        }
      } catch (e) {
        if (active)
          setError(
            e instanceof Error
              ? e.message
              : "Could not restore this workspace.",
          );
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [access?.workspaceId]);
  useEffect(() => {
    document.getElementById("main-title")?.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }, [
    step,
    nav,
    Boolean(state?.speaker.provisional),
    Boolean(state?.importProposal),
  ]);
  useEffect(() => {
    if (error) document.getElementById("alpha-error")?.focus();
  }, [error]);
  useEffect(() => {
    if (
      reviewField &&
      nav === "Ideas" &&
      state?.profileSetup.stage === "review"
    ) {
      document.getElementById("profile-field-" + reviewField)?.focus();
      setReviewField(null);
    }
  }, [nav, state?.profileSetup.stage, reviewField]);
  async function act(action: string, payload: Record<string, unknown> = {}) {
    if (!access || !snapshot || lock.current) return;
    const focusOrigin = document.activeElement as HTMLElement | null;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const next = await api.act(access, snapshot.revision, action, payload);
      setSnapshot(next);
      setConflict(false);
      if (action === "preference")
        requestAnimationFrame(() =>
          (
            document.getElementById(`preference-${payload.preferenceId}`) ||
            document.getElementById("main-title")
          )?.focus({ preventScroll: true }),
        );
      else
        requestAnimationFrame(() => {
          if (document.activeElement === document.body)
            (focusOrigin?.isConnected
              ? focusOrigin
              : document.getElementById("main-title")
            )?.focus({ preventScroll: true });
        });
      return next;
    } catch (e) {
      setError(e instanceof Error ? e.message : "The local action failed.");
      setConflict(e instanceof ApiError && e.status === 409);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function start(sample: boolean) {
    if (!sample) {
      setAuthOpen(true);
      setError("");
      return;
    }
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const next = await api.create(sample);
      const a = { workspaceId: next.workspaceId, token: next.token };
      // Keep the personal workspace access separately when exploring a sample.
      if (access && state && !state.workspace.sample)
        writeLocal("postriff-alpha-personal-access", access);
      writeLocal(ACCESS_KEY, a);
      if (!sample) writeLocal("postriff-alpha-personal-access", a);
      setAccess(a);
      setSnapshot(next);
      setNav("Ideas");
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Could not create a private workspace.",
      );
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function reload() {
    if (!access) return;
    try {
      setSnapshot(await api.get(access));
      setError("");
      setConflict(false);
      setNotice(
        "Loaded the saved version. Unsent text is still in your editor.",
      );
    } catch (e) {
      setError(String(e));
    }
  }
  async function exportPack() {
    if (!access || busy) return;
    setBusy(true);
    setError("");
    try {
      const blob = await api.export(access);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "postriff-private-drafts.zip";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setDownloads((n) => n + 1);
      setNotice(
        "Your private export is ready for download. It includes your saved profile, sources and drafts; exporting does not approve or publish them.",
      );
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Export failed. Your saved work is intact.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function exportVoice() {
    if (!access || busy) return;
    setBusy(true);
    try {
      const blob = await api.exportProfile(access);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "postriff-personal-voice.zip";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice(
        "Your current approved Personal Voice Package is ready for download.",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Profile export failed.");
    } finally {
      setBusy(false);
    }
  }
  function go(destination: string) {
    setNav(destination);
    setMenu(false);
    setError("");
  }
  function reviewVoice(fieldId?: string) {
    setReviewField(fieldId || null);
    void act(
      state?.profileSetup.approved ? "profile_review_open" : "step",
      state?.profileSetup.approved
        ? {}
        : { step: state?.brandHub.mode ? 1 : 0 },
    ).then(() => go("Ideas"));
  }
  function restorePersonal() {
    const a = readLocal<Access | null>("postriff-alpha-personal-access", null);
    if (a) {
      writeLocal(ACCESS_KEY, a);
      setAccess(a);
      setSnapshot(null);
      setLoading(true);
    } else void start(false);
  }
  async function clearSession() {
    try {
      if (authMode === "supabase") await signOutHosted();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not close the hosted session.",
      );
      return;
    }
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem("postriff-alpha-personal-access");
    setAccess(null);
    setSnapshot(null);
    setNav("Ideas");
  }
  const back = (n: number) => () => {
    void act("step", { step: n });
  };
  const profile = state?.speaker.revisions.find(
    (r) => r.revision === state.speaker.activeRevision,
  )?.profile;
  const disabled = loading || busy;
  let content: ReactNode;
  if (authOpen)
    content = (
      <AuthEntry
        phase2={phase2}
        authMode={authMode === "supabase" ? "supabase" : undefined}
        cancel={() => setAuthOpen(false)}
        onError={setError}
        done={(result) => {
          const a: Access = {
            workspaceId: result.workspaceId,
            token: result.token,
            ...(authMode === "supabase"
              ? { authMode: "supabase" as const }
              : {}),
          };
          writeLocal(ACCESS_KEY, a);
          writeLocal("postriff-alpha-personal-access", a);
          setAccess(a);
          setSnapshot(result);
          setAuthOpen(false);
          setNav(result.state.session.completed ? "Dashboard" : "Ideas");
          setError("");
        }}
      />
    );
  else if (loading)
    content = (
      <div className="loading" role="status">
        Opening your private agency…
      </div>
    );
  else if (!state) content = <Welcome start={start} busy={busy} />;
  else if (
    state.workspace.sample &&
    (nav === "Ideas" ||
      nav === "Dashboard" ||
      nav === "You" ||
      nav === "Skills")
  )
    content = (
      <SamplePreview
        state={state}
        start={() => void start(false)}
        exportPack={exportPack}
      />
    );
  else if (nav === "Dashboard")
    content = (
      <Dashboard
        state={state}
        resume={() => go("Ideas")}
        start={() => void act("step", { step: 2 }).then(() => go("Ideas"))}
      />
    );
  else if (nav === "Skills")
    content = (
      <Skills state={state} templates={templates} act={act} busy={busy} />
    );
  else if (nav === "Channels" && state.phase2)
    content = <Channels state={state} busy={busy} act={act} />;
  else if (nav === "Scheduling" && state.phase2)
    content = (
      <Scheduling
        state={state}
        busy={busy}
        act={act}
        reload={async () => {
          if (access && !lock.current) {
            try {
              setSnapshot(await api.get(access));
            } catch {
              /* action boundary reports session errors */
            }
          }
        }}
      />
    );
  else if (nav === "You")
    content = (
      <YouProfile
        key={state.workspace.id + "you"}
        state={state}
        profile={profile}
        templates={templates}
        act={act}
        busy={busy}
        review={reviewVoice}
        openSkills={() => go("Skills")}
        exportProfile={exportVoice}
        account={
          state.phase2 ? (
            <Privacy
              state={state}
              busy={busy}
              act={act}
              exportPack={exportPack}
              hosted={authMode === "supabase"}
              signOut={() => void clearSession()}
            />
          ) : (
            <Settings
              embedded
              state={state}
              profile={profile}
              act={act}
              startSample={() => void start(true)}
              restorePersonal={restorePersonal}
              busy={busy}
              onError={setError}
              signOut={() => void clearSession()}
              reviewVoice={() => reviewVoice()}
            />
          )
        }
      />
    );
  else if (nav !== "Ideas")
    content = <Placeholder title={nav} back={() => go("Ideas")} />;
  else if (step === 0)
    content = (
      <ChooseMode
        key={state.workspace.id + "mode"}
        state={state}
        act={act}
        busy={busy}
      />
    );
  else if (step === 1)
    content = profileMetadata ? (
      <AgentOnboarding
        key={state.workspace.id + "profile"}
        state={state}
        metadata={profileMetadata}
        act={act}
        busy={busy}
        onError={setError}
        exportProfile={exportVoice}
      />
    ) : (
      <p role="alert">
        Profile questions could not load. Refresh the local alpha.
      </p>
    );
  else if (step === 2)
    content = (
      <SourceStep
        key={state.workspace.id + "sources"}
        state={state}
        act={act}
        back={back(1)}
        busy={busy}
        onError={setError}
      />
    );
  else if (step === 3)
    content = (
      <VoiceStep
        key={state.workspace.id + "voice"}
        state={state}
        act={act}
        back={back(2)}
        busy={busy}
      />
    );
  else if (step === 4)
    content = (
      <Runtime
        state={state}
        act={act}
        back={back(state.profileSetup.approved ? 1 : 3)}
        busy={busy}
      />
    );
  else if (step === 5)
    content = (
      <DraftStudio
        key={state.workspace.id + "studio"}
        state={state}
        act={act}
        busy={busy}
        back={back(4)}
      />
    );
  else
    content = (
      <Ready
        state={state}
        profile={profile}
        busy={busy}
        edit={back(5)}
        exportPack={exportPack}
        downloads={downloads}
        review={() => go("You")}
      />
    );
  return (
    <div className="alpha-app">
      <a className="skip-link" href="#main-title">
        Skip to content
      </a>
      <aside
        className={`sidebar ${menu ? "is-open" : ""}`}
        aria-label="Agency navigation"
      >
        <a
          className="wordmark"
          href="#main-title"
          onClick={() => (state ? go("Dashboard") : undefined)}
        >
          <span className="brand-mark" aria-hidden="true">
            p<span>r</span>
          </span>
          PostRiff<span className="wordmark-dot">®</span>
        </a>
        <div className="workspace-label">
          <span className="avatar" aria-hidden="true">
            {state?.workspace.sample ? "S" : "M"}
          </span>
          <span>
            {state?.workspace.name || "Your agency"}
            <small>
              {phase2 ? "Phase 2 · local fixtures" : "Private founder alpha"}
            </small>
          </span>
          <span className="local-dot" aria-label="Local only" />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {NAV.map((item, i) => (
            <button
              key={item}
              className={`nav-item ${nav === item ? "active" : ""}`}
              aria-current={nav === item ? "page" : undefined}
              onClick={() => go(item)}
            >
              <span className="nav-symbol" aria-hidden="true">
                {["◫", "✳", "▦", "⇄", "▥", "◎"][i]}
              </span>
              {item}
              {item === "Ideas" && !!state?.variants.length && (
                <span className="nav-count">1</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button
            className={`nav-item ${nav === "Skills" ? "active" : ""}`}
            onClick={() => go("Skills")}
          >
            <span className="nav-symbol" aria-hidden="true">
              ✧
            </span>
            Skills library
          </button>
          <button
            className={`nav-item ${nav === "You" ? "active" : ""}`}
            onClick={() => go("You")}
          >
            <span className="nav-symbol" aria-hidden="true">
              ◉
            </span>
            You
          </button>
          <div className="local-card">
            <span className="local-dot" />
            <span>
              Only on this device<small>Your ideas stay here.</small>
            </span>
          </div>
        </div>
      </aside>
      <div className="app-body">
        <div className="topbar">
          <button
            className="menu-toggle"
            aria-label="Toggle navigation"
            aria-expanded={menu}
            onClick={() => setMenu(!menu)}
          >
            ☰
          </button>
          <div className="breadcrumb">
            Your agency <span>/</span> {state ? nav : "Welcome"}
          </div>
          <div className="topbar-right">
            <span className="founder-label">
              {phase2 ? "PHASE 2 · LOCAL" : "FOUNDER ALPHA"}
            </span>
            <span className="avatar small" aria-hidden="true">
              M
            </span>
          </div>
        </div>
        <div className="research-banner">
          <span className="banner-dot" />
          Private prototype · Phase 0 incomplete · Customer demand unvalidated
          {state?.workspace.sample && (
            <strong> · Fictional sample workspace</strong>
          )}
        </div>
        <main
          className={`main ${state && !authOpen && !state.workspace.sample && nav === "Ideas" && step !== 5 && step !== 6 ? "with-progress" : ""}`}
          aria-busy={disabled}
        >
          <div className="main-content">
            {error && (
              <div
                id="alpha-error"
                className="message error"
                role="alert"
                tabIndex={-1}
              >
                {error}
                {conflict && (
                  <Button secondary onClick={() => void reload()}>
                    Reload saved version
                  </Button>
                )}
              </div>
            )}
            {notice && (
              <div className="message success" role="status">
                {notice}
              </div>
            )}
            {content}
            <div className="save-status" role="status">
              {state &&
                (state.workspace.sample
                  ? "Temporary fictional sample · kept in memory only"
                  : busy
                    ? "Saving locally…"
                    : `Confirmed state saved on this device · revision ${snapshot?.revision}`)}
            </div>
          </div>
          {state &&
            !authOpen &&
            !state.workspace.sample &&
            nav === "Ideas" &&
            step !== 5 &&
            step !== 6 && (
              <aside className="progress-rail" aria-label="Onboarding progress">
                <div className="eyebrow">A little setup. A lot more you.</div>
                <ol>
                  {STEPS.map((label, i) => (
                    <li
                      key={label}
                      aria-current={chapter === i ? "step" : undefined}
                      className={
                        i === chapter ? "current" : i < chapter ? "done" : ""
                      }
                    >
                      <span>
                        {i < chapter ? "✓" : String(i + 1).padStart(2, "0")}
                      </span>
                      {label}
                    </li>
                  ))}
                </ol>
                <div className="rail-note">
                  Make a useful first draft.
                  <br />
                  Refine your agency as you go.
                  <span>Everything here is editable.</span>
                </div>
              </aside>
            )}
        </main>
        <footer className="app-footer">
          <span>Ideas are yours. So is the final say.</span>
          <span>Private local prototype · v0.1</span>
        </footer>
      </div>
    </div>
  );
}

function Welcome({
  start,
  busy,
}: {
  start: (sample: boolean) => Promise<void>;
  busy: boolean;
}) {
  return (
    <div className="welcome">
      <div className="welcome-copy">
        <div className="eyebrow">
          <span className="little-star">✳</span> YOUR IDEAS, WITH A LITTLE
          MOMENTUM
        </div>
        <h1 id="main-title" tabIndex={-1}>
          Build your social media agency <em>around your voice.</em>
        </h1>
        <p className="lede">
          PostRiff turns your ideas and source material into content shaped for
          the people and channels you care about. You stay in control of what it
          learns and what gets shared.
        </p>
        <div className="welcome-actions">
          <Button onClick={() => void start(false)} disabled={busy}>
            Set up my agency <span aria-hidden="true">↗</span>
          </Button>
          <button
            className="text-button"
            onClick={() => void start(true)}
            disabled={busy}
          >
            Explore with a sample <span aria-hidden="true">→</span>
          </button>
        </div>
        <div className="welcome-assurance">
          <span>✧ Your voice, provisionally</span>
          <span>↗ Your drafts, portable</span>
        </div>
      </div>
      <div
        className="welcome-art"
        aria-label="An illustration of one source becoming two individual drafts"
      >
        <div className="art-orbit orbit-one" />
        <div className="art-orbit orbit-two" />
        <div className="art-topline">A SMALL IDEA CAN GO PLACES.</div>
        <div className="art-note source-note">
          <span className="paper-label">01 / THE SPARK</span>
          <p>
            Something
            <br />
            worth sharing.
          </p>
          <div className="paper-rule" />
          <span className="handwriting">Start with what you know.</span>
        </div>
        <div className="art-note voice-note">
          <span className="paper-label">02 / YOUR POINT OF VIEW</span>
          <p>
            Make it
            <br />
            <em>sound like you.</em>
          </p>
          <div className="ink-lines">
            <i />
            <i />
            <i />
          </div>
          <span className="paper-footer">
            LinkedIn ↗ <span>EN</span>
          </span>
        </div>
        <div className="art-note variant-note">
          <span className="paper-label">03 / A NEW CONTEXT</span>
          <p lang="zh-Hant">
            讓想法，
            <br />
            多一種表達。
          </p>
          <span className="paper-footer">
            Instagram ↗ <span>繁中</span>
          </span>
        </div>
        <div className="art-bottomline">ONE IDEA. A FEW GOOD RIFFS.</div>
      </div>
      <div className="welcome-bottom">
        <div>
          <b>01</b>
          <span>Bring a starting point</span>
        </div>
        <div>
          <b>02</b>
          <span>Shape your first draft</span>
        </div>
        <div>
          <b>03</b>
          <span>Save what feels like you</span>
        </div>
      </div>
    </div>
  );
}

function ChooseMode({
  state,
  act,
  busy,
}: {
  state: AlphaState;
  act: Act;
  busy: boolean;
}) {
  const [mode, setMode] = useDraft<Mode | "">(
    state.workspace.id + ":mode",
    state.brandHub.mode,
  );
  async function submit(e: FormEvent) {
    e.preventDefault();
    await act("mode", { mode });
  }
  return (
    <>
      <Heading
        eyebrow="01 / YOUR STARTING POINT"
        title="What are you building?"
      >
        A personal voice, a focused topic, a business—or a little of each.
      </Heading>
      <form onSubmit={submit}>
        <fieldset className="mode-grid">
          <legend className="sr-only">Agency starting point</legend>
          {MODES.map((m) => (
            <label
              key={m.id}
              className={`mode-card ${mode === m.id ? "selected" : ""}`}
            >
              <input
                type="radio"
                name="mode"
                value={m.id}
                checked={mode === m.id}
                onChange={() => setMode(m.id)}
                required
              />
              <span className="mode-number">{m.mark}</span>
              <span className="radio-indicator" />
              <strong>{m.name}</strong>
              <span className="mode-description">{m.description}</span>
            </label>
          ))}
        </fieldset>
        <p className="helper">
          This is a starting point, not a permanent account type. You can change
          it later.
        </p>
        <BackNext busy={busy} />
      </form>
    </>
  );
}

function Context({
  state,
  act,
  back,
  busy,
}: {
  state: AlphaState;
  act: Act;
  back: () => void;
  busy: boolean;
}) {
  const mode = state.brandHub.mode || "personal";
  const [fields, setFields] = useDraft<FormFields>(
    state.workspace.id + ":context:" + mode,
    {
      purpose: state.brandHub.purpose,
      audience: state.brandHub.audience,
      subject: state.brandHub.subject,
      speaker: state.brandHub.speaker,
      layers: mode === "hybrid" ? state.brandHub.layers : [],
    },
  );
  const prompts = {
    personal:
      "What do you want people to know you for, and who do you hope to help?",
    niche: "What subject do you want to build around, and who should it help?",
    business: "What does your business help people do, and who is it for?",
    hybrid: "Which parts of your world should this agency bring together?",
  };
  const set = (key: string, value: string | string[]) =>
    setFields({ ...fields, [key]: value });
  async function submit(e: FormEvent) {
    e.preventDefault();
    await act("context", fields);
  }
  return (
    <>
      <Heading
        eyebrow="02 / PURPOSE & AUDIENCE"
        title="Give your agency a direction."
      >
        {prompts[mode]}
      </Heading>
      <form onSubmit={submit} className="context-form">
        {mode === "hybrid" && (
          <fieldset className="layer-picker">
            <legend>Choose at least two building blocks</legend>
            {[
              ["voice", "My voice"],
              ["niche", "A niche"],
              ["business", "A business"],
            ].map(([id, label]) => (
              <label key={id}>
                <input
                  type="checkbox"
                  checked={(fields.layers as string[]).includes(id)}
                  onChange={(e) =>
                    set(
                      "layers",
                      e.target.checked
                        ? [...(fields.layers as string[]), id]
                        : (fields.layers as string[]).filter((x) => x !== id),
                    )
                  }
                />
                {label}
              </label>
            ))}
          </fieldset>
        )}
        <label className="field">
          {mode === "business"
            ? "What you help people do"
            : "What you want to share"}
          <textarea
            value={fields.purpose as string}
            onChange={(e) => set("purpose", e.target.value)}
            maxLength={1500}
            required
            rows={3}
            placeholder={
              mode === "business"
                ? "We make it easier for…"
                : "I want to help people understand…"
            }
          />
        </label>
        <label className="field">
          Who is this for?
          <input
            value={fields.audience as string}
            onChange={(e) => set("audience", e.target.value)}
            maxLength={1500}
            required
            placeholder="A group of people you can picture"
          />
        </label>
        {mode !== "personal" && (
          <label className="field">
            {mode === "business" ? "Business or offer" : "Subject or business"}
            <input
              value={fields.subject as string}
              onChange={(e) => set("subject", e.target.value)}
              maxLength={1500}
              required
              placeholder="A concrete subject, service, or product"
            />
          </label>
        )}
        {mode === "hybrid" && (
          <label className="field">
            Who should be speaking in this first post?
            <select
              value={fields.speaker as string}
              onChange={(e) => set("speaker", e.target.value)}
              required
            >
              <option value="">Choose the speaker</option>
              <option>My voice</option>
              <option>The business</option>
              <option>A neutral editor</option>
            </select>
          </label>
        )}
        <div className="interpretation">
          <span className="little-star">✧</span>
          <div>
            <strong>A starting direction, in your words</strong>
            <p>
              {fields.purpose || "Your purpose will appear here."}
              {fields.audience ? ` For ${fields.audience}.` : ""}
            </p>
            <span className="helper">
              These answers stay editable. No biography or expertise is
              inferred.
            </span>
          </div>
        </div>
        <BackNext back={back} busy={busy} />
      </form>
    </>
  );
}

function SourceReview({
  source,
  act,
  busy,
}: {
  source: Source;
  act: Act;
  busy: boolean;
}) {
  const [selected, setSelected] = useState(
    source.facts.filter((f) => f.approved).map((f) => f.id),
  );
  return (
    <section className="source-review">
      <div className="source-header">
        <h3>{source.title}</h3>
        <Tag>{source.reviewedAt ? "Reviewed" : "Needs your review"}</Tag>
      </div>
      {source.facts.length > 0 ? (
        <>
          <p className="helper">
            Approve only statements you can use. Approval does not independently
            verify a source.
          </p>
          <fieldset>
            <legend className="sr-only">Facts from {source.title}</legend>
            {source.facts.map((f) => (
              <label className="fact-row" key={f.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(f.id)}
                  onChange={(e) =>
                    setSelected(
                      e.target.checked
                        ? [...selected, f.id]
                        : selected.filter((x) => x !== f.id),
                    )
                  }
                />
                <span>
                  {f.text}
                  <small>{f.locator} · private source</small>
                </span>
              </label>
            ))}
          </fieldset>
          <Button
            secondary
            disabled={busy}
            onClick={() =>
              void act("approve_source", {
                sourceId: source.id,
                factIds: selected,
              })
            }
          >
            Confirm selected facts
          </Button>
        </>
      ) : (
        <p className="helper">
          {source.kind === "link"
            ? "Reference saved. Link contents were not fetched. Paste text to propose facts."
            : "Saved as an idea, not a verified fact."}
        </p>
      )}
      <button
        type="button"
        className="text-button danger"
        disabled={busy}
        onClick={() => void act("retract_source", { sourceId: source.id })}
      >
        Withdraw this source
      </button>
    </section>
  );
}

function SourceStep({
  state,
  act,
  back,
  busy,
  onError,
}: {
  state: AlphaState;
  act: Act;
  back: () => void;
  busy: boolean;
  onError: (error: string) => void;
}) {
  const [kind, setKind] = useDraft(
    state.workspace.id + ":source-kind",
    state.workspace.sample ? "sample" : "idea",
  );
  const [idea, setIdea] = useDraft(
    state.workspace.id + ":idea",
    state.brief.idea,
  );
  const [sourceText, setSourceText] = useDraft(
    state.workspace.id + ":source-text",
    "",
  );
  const [filename, setFilename] = useState("");
  async function file(file?: File) {
    if (!file) return;
    if (!/\.(txt|md)$/i.test(file.name) || file.size > 20000) {
      onError(
        "This alpha reads UTF-8 .txt and .md files up to 20 KB. Export other documents as text first.",
      );
      return;
    }
    try {
      const decoder = new TextDecoder("utf-8", { fatal: true });
      setSourceText(decoder.decode(await file.arrayBuffer()));
      setFilename(file.name);
    } catch {
      onError(
        "This file is not valid UTF-8 text. Save it as UTF-8 and try again.",
      );
    }
  }
  async function add() {
    const result = await act("source", {
      kind:
        kind === "paste"
          ? sourceText.match(/^https?:\/\/\S+$/)
            ? "link"
            : "text"
          : kind,
      text: sourceText,
      title: kind === "document" ? filename : "Source note",
    });
    if (result && !idea) setIdea(result.state.brief.idea);
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (idea !== state.brief.idea) {
      const next = await act("idea", { idea });
      if (next) return;
    }
    await act("source_done");
  }
  return (
    <>
      <Heading
        eyebrow="03 / YOUR FIRST IDEA"
        title="What would you like to create first?"
      >
        PostRiff will separate source facts, your point of view, and anything
        that still needs checking.
      </Heading>
      <ContentTypes state={state} act={act} busy={busy} />
      <div
        className="source-tabs"
        role="group"
        aria-label="Source starting options"
      >
        {[
          ["idea", "Write an idea"],
          ["paste", "Paste a link or text"],
          ["document", "Add a document I can use"],
          ["sample", "Try a sample topic"],
        ].map(([id, label]) => (
          <button
            key={id}
            className={kind === id ? "selected" : ""}
            aria-pressed={kind === id}
            onClick={() => setKind(id)}
          >
            {label}
          </button>
        ))}
      </div>
      {state.brandHub.mode === "business" && (
        <p className="business-hint">
          Start from an offer, service description, FAQ, or product note you
          have permission to use. Approve at least one fact for a business post.
        </p>
      )}
      <form onSubmit={submit}>
        <label className="field">
          Your idea or angle
          <textarea
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            rows={3}
            maxLength={3000}
            placeholder="What is the one thing you want someone to take away?"
          />
        </label>
        {kind === "idea" && (
          <p className="helper">
            An idea can start a draft without being treated as a fact. Add
            source material when you have it.
          </p>
        )}
        {kind === "document" && (
          <label className="upload-zone">
            <span className="upload-arrow" aria-hidden="true">
              ↥
            </span>
            <strong>Add a document you can use</strong>
            <span>UTF-8 .txt or .md · up to 20 KB · stays on this device</span>
            <input
              type="file"
              accept=".txt,.md,text/plain,text/markdown"
              aria-label="Choose source document"
              onChange={(e) => void file(e.target.files?.[0])}
            />
          </label>
        )}
        {(kind === "paste" || kind === "document") && (
          <label className="field">
            {kind === "document"
              ? "Review imported text"
              : "Source text or reference link"}
            <textarea
              rows={5}
              value={sourceText}
              onChange={(e) => setSourceText(e.target.value)}
              maxLength={20000}
              placeholder="Paste material you own or have permission to use."
            />
          </label>
        )}
        {kind === "sample" && (
          <div className="sample-topic">
            <Tag>Fictional sample</Tag>
            <h3>A seed swap for curious beginners</h3>
            <p>
              A community garden is hosting a free Saturday seed swap and a
              planting demonstration.
            </p>
            <span className="helper">
              Sample facts are labeled and require approval. They are not facts
              about you.
            </span>
          </div>
        )}
        {kind !== "idea" && (
          <Button
            type="button"
            secondary
            disabled={busy}
            onClick={() => void add()}
          >
            {kind === "sample"
              ? "Add fictional sample"
              : "Import for fact review"}{" "}
            <span aria-hidden="true">＋</span>
          </Button>
        )}
        {state.sources
          .filter((s) => s.active)
          .map((s) => (
            <SourceReview key={s.id} source={s} act={act} busy={busy} />
          ))}
        {state.sources.some((s) => !s.active) && (
          <p className="helper">
            A withdrawn source is excluded from future drafting and export.
          </p>
        )}
        <BackNext
          back={back}
          label={
            idea !== state.brief.idea
              ? "Confirm idea"
              : state.profileSetup.approved
                ? "Continue to writing setup"
                : "Continue to your voice"
          }
          busy={busy}
        />
      </form>
    </>
  );
}

function VoiceStep({
  state,
  act,
  back,
  busy,
}: {
  state: AlphaState;
  act: Act;
  back: () => void;
  busy: boolean;
}) {
  const [writing, setWriting] = useDraft(
    state.workspace.id + ":writing",
    String(state.session.answers.writing || ""),
  );
  const [tone, setTone] = useDraft<Tone>(state.workspace.id + ":tone", "warm");
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const provisional = state.speaker.provisional;
  return (
    <>
      <Heading
        eyebrow="04 / YOUR VOICE"
        title="How would you explain this in your own words?"
      >
        A few natural sentences are enough. You can also add two or three
        examples of writing you own.
      </Heading>
      {provisional ? (
        <>
          <ProfileCard profile={provisional} />
          <h2 className="question-heading">
            Does this sound like a useful starting point?
          </h2>
          {editing && (
            <label className="field">
              Edit the observations
              <textarea
                autoFocus
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={3}
                maxLength={1500}
              />
            </label>
          )}
          <div className="button-row">
            <Button
              disabled={busy}
              onClick={() =>
                void act("profile_decide", {
                  decision: "approve",
                  note: editing ? note : "",
                })
              }
            >
              Yes, use this ↗
            </Button>
            <Button
              secondary
              disabled={busy}
              onClick={() => {
                setNote(provisional.observations.join("\n"));
                setEditing(true);
              }}
            >
              Edit it
            </Button>
            <button
              className="text-button"
              disabled={busy}
              onClick={() => void act("profile_decide", { decision: "reject" })}
            >
              Start again
            </button>
          </div>
        </>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void act("profile_propose", { writing, tone });
          }}
        >
          <label className="field">
            Write something or add examples
            <textarea
              value={writing}
              onChange={(e) => setWriting(e.target.value)}
              rows={5}
              maxLength={6000}
              placeholder="How would you talk about this to someone you know?"
            />
          </label>
          <label className="field narrow">
            A starting tone
            <select
              value={tone}
              onChange={(e) => setTone(e.target.value as Tone)}
            >
              <option value="warm">Warm and clear</option>
              <option value="direct">Direct and practical</option>
              <option value="reflective">Reflective and curious</option>
            </select>
          </label>
          <p className="helper">
            This fixture records your choices. It does not analyze your writing
            or claim to know your voice.
          </p>
          <BackNext back={back} label="Review my starting voice" busy={busy} />
          <button
            className="text-button skip"
            type="button"
            disabled={busy}
            onClick={() => void act("profile_propose", { writing: "", tone })}
          >
            Skip writing for now
          </button>
        </form>
      )}
    </>
  );
}

function Runtime({
  state,
  act,
  back,
  busy,
}: {
  state: AlphaState;
  act: Act;
  back: () => void;
  busy: boolean;
}) {
  const [choice, setChoice] = useState("later");
  return (
    <>
      <Heading
        eyebrow="05 / WRITING SETUP"
        title="What should power your writing?"
      >
        Choose how to continue. This private alpha can produce a local writing
        preview without calling a model.
      </Heading>
      <fieldset className="runtime-options">
        <legend className="sr-only">Writing runtime</legend>
        {[
          [
            "existing",
            "Use an agent I already have",
            "Codex, Claude, and Google routes are planned; qualification is still pending.",
          ],
          [
            "managed",
            "Use PostRiff managed writing",
            "Unavailable in this alpha. No provider or billing is connected.",
          ],
          [
            "later",
            "Decide later",
            "Explore with deterministic drafts made from your approved material.",
          ],
        ].map(([id, name, description]) => (
          <label
            className={
              choice === id ? "runtime-choice selected" : "runtime-choice"
            }
            key={id}
          >
            <input
              type="radio"
              name="runtime"
              checked={choice === id}
              onChange={() => setChoice(id)}
            />
            <span>
              <strong>{name}</strong>
              <small>{description}</small>
            </span>
          </label>
        ))}
      </fieldset>
      {choice !== "later" && (
        <div className="runtime-status">
          <h2>Route qualification</h2>
          {state.runtime.routes
            .filter((r) =>
              choice === "managed"
                ? r.id === "managed"
                : ["codex", "claude", "google"].includes(r.id),
            )
            .map((r) => (
              <div key={r.id}>
                <strong>{r.label}</strong>
                <Tag>{r.status}</Tag>
                <p>{r.detail}</p>
              </div>
            ))}
        </div>
      )}
      <div className="preview-note">
        <span className="little-star">✳</span>
        <p>
          <strong>For now: deterministic writing preview</strong>
          <br />
          Authored templates, approved facts, and no model call. No credits used
          and no automatic paid fallback. Custom source quotes are preserved;
          translation needs review.
        </p>
      </div>
      <div className="form-actions">
        <Button secondary onClick={back}>
          ← Back
        </Button>
        <Button
          disabled={busy}
          onClick={() =>
            void act("runtime", { selected: "deterministic-preview" })
          }
        >
          Continue with local preview ↗
        </Button>
      </div>
    </>
  );
}

function DraftStudio({
  state,
  act,
  busy,
  back,
}: {
  state: AlphaState;
  act: Act;
  busy: boolean;
  back: () => void;
}) {
  const [platform, setPlatform] = useState<Platform>("LinkedIn");
  const [language, setLanguage] = useState<Language>("English");
  const [showBrief, setShowBrief] = useState(false);
  const [idea, setIdea] = useDraft(
    state.workspace.id + ":brief-editor",
    state.brief.idea,
  );
  const [failure, setFailure] = useState("timeout");
  const lastRun = state.runs.at(-1);
  const profile = state.speaker.revisions.find(
    (x) => x.revision === state.speaker.activeRevision,
  )?.profile;
  function generate() {
    const result = act("generate", { platform, language });
    void result.then((next) => {
      if (next?.state.variants.length === 1) {
        setPlatform("Instagram");
        setLanguage("繁體中文");
      }
    });
  }
  return (
    <>
      <div className="studio-title">
        <Heading
          eyebrow="06 / MAKE IT YOURS"
          title={
            state.variants.length
              ? "One idea. A few good riffs."
              : "Let’s give your idea a first shape."
          }
        >
          A draft to work with. Your judgment makes it yours.
        </Heading>
        <Tag>Deterministic preview · no model called</Tag>
      </div>
      <ContentTypes state={state} act={act} busy={busy} compact />
      <div className="brief-strip">
        <span className="little-star">✳</span>
        <div>
          <div className="eyebrow">
            YOUR SHARED IDEA · REVISION {state.brief.revision}
          </div>
          <p>{state.brief.idea}</p>
          <small>
            {state.brandHub.speaker} · {state.brandHub.audience}
          </small>
        </div>
        <button
          className="text-button"
          onClick={() => setShowBrief(!showBrief)}
        >
          {showBrief ? "Close" : "Edit brief"}
        </button>
      </div>
      {showBrief && (
        <div className="brief-editor">
          <label className="field">
            Shared idea
            <textarea
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              rows={3}
              maxLength={3000}
            />
          </label>
          <p className="helper">
            Changing the brief proposes updates. Each existing draft stays
            intact until you accept its replacement.
          </p>
          <Button
            secondary
            disabled={busy}
            onClick={() => void act("idea", { idea })}
          >
            Propose draft updates
          </Button>
        </div>
      )}
      <div className="draft-layout">
        <div className="draft-column">
          {lastRun?.status === "failed" && (
            <div className="message error" role="alert">
              <strong>Simulated {lastRun.failure}</strong>
              <p>{lastRun.message}</p>
            </div>
          )}
          {!state.variants.length && (
            <div className="empty-draft">
              <span className="draft-star" aria-hidden="true">
                ✳
              </span>
              <h2>Your first draft starts here.</h2>
              <p>
                Pick a platform and language below. The preview uses approved
                source statements and clearly marks anything missing.
              </p>
            </div>
          )}
          {state.variants.map((v, i) => (
            <VariantEditor
              key={v.id}
              variant={v}
              number={i + 1}
              state={state}
              act={act}
              busy={busy}
            />
          ))}
          <section className="adapt-panel">
            <div>
              <div className="eyebrow">
                {state.variants.length
                  ? "ANOTHER WAY IN"
                  : "YOUR FIRST VERSION"}
              </div>
              <h2>
                {state.variants.length
                  ? "Where else should PostRiff adapt this idea?"
                  : "Choose where this idea belongs."}
              </h2>
            </div>
            <div className="adapt-controls">
              <label className="field">
                Platform
                <select
                  value={platform}
                  onChange={(e) => setPlatform(e.target.value as Platform)}
                >
                  {["LinkedIn", "Instagram", "Threads"].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                Language
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value as Language)}
                >
                  <option>English</option>
                  <option>繁體中文</option>
                </select>
              </label>
              <Button disabled={busy} onClick={generate}>
                {state.variants.length
                  ? "Create another variant"
                  : "Create first draft"}{" "}
                <span aria-hidden="true">↗</span>
              </Button>
            </div>
            <p className="helper">
              Each version has its own structure, copy, source references, and
              revision history. Fictional sample facts have reviewed bilingual
              wording.
            </p>
          </section>
          <div className="form-actions">
            <Button secondary onClick={back} disabled={busy}>
              ← Writing setup
            </Button>
            <Button
              disabled={busy || state.variants.length < 2}
              onClick={() => void act("save")}
            >
              Save in Ideas ↗
            </Button>
          </div>
        </div>
        <aside className="draft-aside">
          {profile && (
            <ProfileCard
              profile={profile}
              title={`Voice · revision ${state.speaker.activeRevision}`}
            />
          )}
          <section className="source-ledger">
            <div className="eyebrow">GROUNDING THIS IDEA</div>
            <h2>Source notes</h2>
            {state.sources.filter((s) => s.active).length ? (
              state.sources
                .filter((s) => s.active)
                .map((s) => (
                  <div key={s.id}>
                    <strong>{s.title}</strong>
                    <p>
                      {s.facts.filter((f) => f.approved).length} approved facts
                      · {s.kind}
                    </p>
                    {s.unknowns.map((u, i) => (
                      <small key={i}>{u}</small>
                    ))}
                  </div>
                ))
            ) : (
              <p>No factual source supplied. This is an idea outline.</p>
            )}
            <button
              className="text-button"
              disabled={busy}
              onClick={() => void act("step", { step: 2 })}
            >
              Review sources →
            </button>
          </section>
          <details className="diagnostics">
            <summary>Local runtime checks</summary>
            <p className="helper">
              Simulated recovery states. These do not test a real provider.
            </p>
            <label className="field">
              Fixture failure
              <select
                value={failure}
                onChange={(e) => setFailure(e.target.value)}
              >
                {[
                  "timeout",
                  "cancelled",
                  "malformed",
                  "quota",
                  "missing",
                  "unauthenticated",
                  "unsupported",
                ].map((f) => (
                  <option key={f}>{f}</option>
                ))}
              </select>
            </label>
            <Button
              secondary
              disabled={busy}
              onClick={() =>
                void act("generate", {
                  platform: "Threads",
                  language: "English",
                  fixtureFailure: failure,
                })
              }
            >
              Simulate failure
            </Button>
            <p className="helper">
              {state.runs.length} local run records. Real agent routes:
              untested. Managed writing: blocked.
            </p>
          </details>
        </aside>
      </div>
    </>
  );
}

function VariantEditor({
  variant: v,
  number,
  state,
  act,
  busy,
}: {
  variant: Variant;
  number: number;
  state: AlphaState;
  act: Act;
  busy: boolean;
}) {
  const draftKey = state.workspace.id + ":variant:" + v.id;
  const [text, setText] = useDraft(draftKey, v.text);
  const prior = useRef(v.text);
  const [showOpenings, setShowOpenings] = useState(number === 1);
  const [ownOpening, setOwnOpening] = useState(false);
  const [replace, setReplace] = useState(false);
  const editor = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (v.text !== prior.current) {
      setText(v.text);
      prior.current = v.text;
    }
  }, [v.text]);
  const preferences = state.preferences.filter(
    (p) => p.variantId === v.id && p.status !== "deleted",
  );
  return (
    <article className="draft-card">
      <div className="draft-header">
        <div>
          <span className="draft-number">
            {String(number).padStart(2, "0")}
          </span>
          <h2>{v.platform}</h2>
          <Tag>{v.language}</Tag>
        </div>
        <span className="revision-label">
          v{v.revision}
          {v.customized ? " · Edited" : ""}
        </span>
      </div>
      {v.needsReview && (
        <div className="review-banner">
          <strong>
            {v.blockedByRetraction
              ? "A source was withdrawn."
              : "The shared brief or profile changed."}
          </strong>
          <p>
            Your current draft is preserved. Review a replacement before saving
            or exporting.
          </p>
          {replace ? (
            <div>
              <p>
                Review this proposed replacement. Your prior edit remains in
                local revision history.
              </p>
              {v.proposedUpdate ? (
                <div
                  className="candidate-copy"
                  lang={v.language === "繁體中文" ? "zh-Hant" : "en"}
                >
                  {v.proposedUpdate.text}
                </div>
              ) : (
                <p role="status">Preparing the local preview…</p>
              )}
              <Button
                secondary
                disabled={busy || !v.proposedUpdate}
                onClick={() =>
                  void act("accept_update", { variantId: v.id }).then(() =>
                    setReplace(false),
                  )
                }
              >
                Accept replacement
              </Button>
              <button className="text-button" onClick={() => setReplace(false)}>
                Keep editing
              </button>
            </div>
          ) : (
            <Button
              secondary
              disabled={busy}
              onClick={() =>
                void act("preview_update", { variantId: v.id }).then((next) => {
                  if (next) setReplace(true);
                })
              }
            >
              Review proposed update
            </Button>
          )}
        </div>
      )}
      <label className="field draft-field">
        <span className="sr-only">
          {v.platform} {v.language} draft
        </span>
        <textarea
          ref={editor}
          lang={v.language === "繁體中文" ? "zh-Hant" : "en"}
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={Math.max(9, Math.min(18, text.split("\n").length + 2))}
          maxLength={20000}
        />
      </label>
      <div className="draft-toolbar">
        <span>
          {text.length} characters · Voice r{v.voiceRevision} · Brief r
          {v.briefRevision}
        </span>
        <Button
          secondary
          disabled={busy || text === v.text}
          onClick={() =>
            void act("variant_edit", {
              variantId: v.id,
              variantRevision: v.revision,
              text,
            })
          }
        >
          Save edit
        </Button>
      </div>
      {ownOpening && (
        <p className="helper">
          Write your own opening in the editor, then save the edit. No voice
          preference is assumed.
        </p>
      )}
      <button
        className="opening-toggle"
        aria-expanded={showOpenings}
        onClick={() => setShowOpenings(!showOpenings)}
      >
        Which opening feels most like you?{" "}
        <span>{showOpenings ? "−" : "+"}</span>
      </button>
      {showOpenings && (
        <div className="openings">
          <div className="helper">
            Current opening and two alternatives. Choosing one only changes this
            draft.
          </div>
          {v.openings.map((opening, i) => (
            <button
              key={opening}
              className={v.selectedOpening === i ? "chosen" : ""}
              disabled={busy}
              aria-pressed={v.selectedOpening === i}
              onClick={() => void act("opening", { variantId: v.id, index: i })}
            >
              <span>{String(i + 1).padStart(2, "0")}</span>
              <span lang={v.language === "繁體中文" ? "zh-Hant" : "en"}>
                {opening}
              </span>
              <span aria-hidden="true">↗</span>
            </button>
          ))}
          <button
            className="text-button"
            onClick={() => {
              setOwnOpening(true);
              editor.current?.focus();
            }}
          >
            None of these — I’ll edit my own
          </button>
        </div>
      )}
      {preferences.map((p) => (
        <div
          className="preference"
          id={`preference-${p.id}`}
          tabIndex={-1}
          key={p.id}
        >
          <span className="little-star">✧</span>
          <div>
            <strong>{p.label}</strong>
            {p.status === "proposed" ? (
              <>
                <p>
                  One optional suggestion after your edit. It only becomes a
                  future writing preference if you choose to remember it.
                </p>
                <div className="button-row">
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void act("preference", {
                        preferenceId: p.id,
                        decision: "remember",
                      })
                    }
                  >
                    Remember this
                  </Button>
                  <Button
                    secondary
                    disabled={busy}
                    onClick={() =>
                      void act("preference", {
                        preferenceId: p.id,
                        decision: "post-only",
                      })
                    }
                  >
                    Only for this post
                  </Button>
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() =>
                      void act("preference", {
                        preferenceId: p.id,
                        decision: "reject",
                      })
                    }
                  >
                    Don’t use this
                  </button>
                </div>
              </>
            ) : (
              <>
                <p>
                  {p.status === "remembered"
                    ? `Remembered for ${p.language} ${p.platform}.`
                    : p.status === "post-only"
                      ? "Applies to this post only; your voice profile is unchanged."
                      : p.status === "rejected"
                        ? "Suggestion rejected. Your voice profile is unchanged."
                        : "Preference removed from your active voice."}
                </p>
                {p.status === "remembered" && (
                  <div className="button-row">
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() =>
                        void act("preference", {
                          preferenceId: p.id,
                          decision: "undo",
                        })
                      }
                    >
                      Undo
                    </button>
                    <button
                      className="text-button danger"
                      disabled={busy}
                      onClick={() =>
                        void act("preference", {
                          preferenceId: p.id,
                          decision: "delete",
                        })
                      }
                    >
                      Delete preference
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      ))}
      <details className="source-details">
        <summary>
          {v.sourceIds.length} linked sources · notes & unknowns
        </summary>
        <ul>
          {[...v.warnings, ...v.unknowns].map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      </details>
    </article>
  );
}

function Ready({
  state,
  profile,
  busy,
  edit,
  exportPack,
  downloads,
  review,
}: {
  state: AlphaState;
  profile?: Profile;
  busy: boolean;
  edit: () => void;
  exportPack: () => Promise<void>;
  downloads: number;
  review: () => void;
}) {
  return (
    <>
      <div className="ready-check" aria-hidden="true">
        ✓
      </div>
      <Heading
        eyebrow="07 / SAVED IN IDEAS"
        title="Your first PostRiff is ready."
      >
        One idea, {state.variants.length} versions, and a starting voice that
        belongs to you.
      </Heading>
      <div className="ready-grid">
        <section className="pack-summary">
          <div className="eyebrow">YOUR SAVED CONTENT PACK</div>
          <h2>{state.brief.idea}</h2>
          {state.variants.map((v) => (
            <div className="saved-variant" key={v.id}>
              <span>{v.platform}</span>
              <Tag>{v.language}</Tag>
              <small>Draft v{v.revision}</small>
            </div>
          ))}
          <p className="helper">
            Saved{" "}
            {state.savedAt ? new Date(state.savedAt).toLocaleString() : ""} on
            this device.
          </p>
          <div className="button-row">
            <Button disabled={busy} onClick={() => void exportPack()}>
              Export drafts ↗
            </Button>
            <Button secondary disabled={busy} onClick={edit}>
              Continue editing
            </Button>
          </div>
          <p className="helper">
            ZIP includes VOICE.md, BRAND.md, neutral SKILL.md references,
            profile.json, source manifest and your drafts.
            {downloads > 0 ? " Download prepared." : ""}
          </p>
        </section>
        {profile && <ProfileCard profile={profile} />}
      </div>
      <button className="text-button" onClick={review}>
        Review what PostRiff learned →
      </button>
      <div className="next-time">
        <span className="little-star">✳</span>
        <div>
          <h2>Come back to an agency that remembers your choices.</h2>
          <p>
            Your confirmed answers, drafts and approved preferences will be here
            when you return on this browser and device.
          </p>
          <p className="helper">
            Connect a channel later. Scheduling and publishing are outside this
            alpha.
          </p>
        </div>
      </div>
    </>
  );
}

function Dashboard({
  state,
  resume,
  start,
}: {
  state: AlphaState;
  resume: () => void;
  start: () => void;
}) {
  return (
    <>
      <Heading
        eyebrow="YOUR PRIVATE WORKSPACE"
        title={
          state.session.completed
            ? "Welcome back to your agency."
            : "A little progress, ready to continue."
        }
      >
        Your ideas and the choices you approved, in one place.
      </Heading>
      <div className="dashboard-metrics">
        <div>
          <b>{state.variants.length ? 1 : 0}</b>
          <span>Idea in progress</span>
        </div>
        <div>
          <b>{state.variants.length}</b>
          <span>Individual drafts</span>
        </div>
        <div>
          <b>
            {state.preferences.filter((p) => p.status === "remembered").length}
          </b>
          <span>Approved preferences</span>
        </div>
      </div>
      <section className="continue-card">
        <div className="eyebrow">PICK UP WHERE YOU LEFT OFF</div>
        <h2>{state.brief.idea || "Your agency is taking shape."}</h2>
        <p>
          {state.variants.length
            ? state.variants
                .map((v) => `${v.platform} · ${v.language}`)
                .join(" / ")
            : [
                "Your agency",
                "Your AI and profile",
                "Your first idea",
                "Your voice",
                "Writing setup",
                "Drafts",
                "Saved pack",
              ][state.session.step]}
        </p>
        <Button onClick={resume}>Continue your last idea ↗</Button>
      </section>
      <div className="next-question">
        <h2>What would you like to create next?</h2>
        <p>
          For this founder alpha, explore a new direction by revising the
          current brief. Existing variants stay intact until you review their
          updates.
        </p>
        <button className="text-button" onClick={start}>
          Revisit your idea and sources →
        </button>
      </div>
      <div className="research-note">
        <strong>Research stays open.</strong>
        <p>
          Phase 0 is incomplete. P02–P05 remain pending; interviews resume after
          the prototype is ready for testing. This alpha is not
          customer-validation evidence.
        </p>
      </div>
    </>
  );
}

function Skills({
  state,
  templates,
  act,
  busy,
}: {
  state: AlphaState;
  templates: Template[];
  act: Act;
  busy: boolean;
}) {
  const [plan, setPlan] = useState("Starter");
  return (
    <>
      <Heading
        eyebrow="YOUR AGENCY’S TOOLS"
        title="A small library. Shaped around you."
      >
        Neutral templates provide a starting structure. Your configuration is a
        private instance in this workspace.
      </Heading>
      <div className="library-controls">
        <label className="field">
          Plan preview fixture
          <select value={plan} onChange={(e) => setPlan(e.target.value)}>
            {["Starter", "Creator", "Starter trial", "Creator trial"].map(
              (p) => (
                <option key={p}>{p}</option>
              ),
            )}
          </select>
        </label>
        <span>
          {templates.length} of {templates.length} released skills available ·
          all plans and trials
        </span>
      </div>
      <div className="skill-list">
        {templates.map((t, i) => {
          const instance = state.skillInstances.find(
            (s) => s.templateId === t.id,
          );
          return (
            <article key={t.id} className="skill-row">
              <span className="skill-number">
                {String(i + 1).padStart(2, "0")}
              </span>
              <div className="skill-body">
                <div className="skill-title">
                  <h2>{t.name}</h2>
                  <Tag>v{instance?.templateVersion || t.version}</Tag>
                </div>
                <p>{t.description}</p>
                <details>
                  <summary>Template & private configuration</summary>
                  <ul>
                    {t.instructions.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                  <p className="helper">Public-safe example: {t.example}</p>
                  {Object.entries(t.configurationSchema).map(([key, field]) => (
                    <label className="field narrow" key={key}>
                      {key === "shortOpenings"
                        ? "Prefer short openings"
                        : key === "sourceNotes"
                          ? "Include source notes"
                          : key === "guidance"
                            ? "Guidance style"
                            : "Starting tone"}
                      {field.type === "boolean" ? (
                        <select
                          value={String(
                            instance?.overrides[key] ?? field.default,
                          )}
                          disabled={busy}
                          onChange={(e) =>
                            void act("template_config", {
                              templateId: t.id,
                              overrides: { [key]: e.target.value === "true" },
                            })
                          }
                        >
                          <option value="true">Yes</option>
                          <option value="false">No</option>
                        </select>
                      ) : (
                        <select
                          value={String(
                            instance?.overrides[key] ?? field.default,
                          )}
                          disabled={busy}
                          onChange={(e) =>
                            void act("template_config", {
                              templateId: t.id,
                              overrides: { [key]: e.target.value },
                            })
                          }
                        >
                          {field.values?.map((v) => (
                            <option key={v} value={v}>
                              {v}
                            </option>
                          ))}
                        </select>
                      )}
                    </label>
                  ))}
                  <p className="helper">
                    Tone and opening preferences affect future fixture runs.
                    Guidance and source-note settings are stored for future
                    adapters; this alpha keeps safety notes visible.
                  </p>
                  <p className="helper">
                    Dependencies: {t.dependencies.join(", ") || "None"}
                  </p>
                </details>
              </div>
            </article>
          );
        })}
      </div>
      <Button
        secondary
        disabled={busy}
        onClick={() => void act("template_refresh")}
      >
        Refresh template references
      </Button>
      <p className="helper">
        Private overrides survive template refreshes. This preview has no
        billing or skill entitlement restrictions.
      </p>
    </>
  );
}

function Settings({
  state,
  profile,
  act,
  startSample,
  restorePersonal,
  busy,
  onError,
  reviewVoice,
  signOut,
  embedded = false,
}: {
  embedded?: boolean;
  state: AlphaState;
  profile?: Profile;
  act: Act;
  startSample: () => void;
  restorePersonal: () => void;
  busy: boolean;
  onError: (error: string) => void;
  reviewVoice: () => void;
  signOut: () => void;
}) {
  async function importFile(file?: File) {
    if (!file) return;
    if (file.size > 40000) {
      onError("Choose a profile.json under 40 KB.");
      return;
    }
    try {
      await act("import_propose", { content: JSON.parse(await file.text()) });
    } catch {
      onError(
        "This is not valid profile JSON. Choose profile.json from a PostRiff export.",
      );
    }
  }
  return (
    <>
      {!embedded && (
        <Heading eyebrow="ACCOUNT & PRIVACY" title="You decide what stays.">
          Your profile is editable data. It cannot authorize tools, account
          access, payments, or publishing.
        </Heading>
      )}
      <section className="settings-section">
        <h2>Your PostRiff account preview</h2>
        <p>
          {state.account
            ? `${state.account.displayName} · Simulated verified user · ${state.membership?.role} of this private workspace`
            : "Legacy local workspace credential · no production account"}
        </p>
        <p className="helper">
          User identity, owner membership, local device credential, AI
          relationship, runtime capability and social connections are separate
          records. Real account linking, recovery, cloud pairing and production
          verification are not enabled.
        </p>
        <button className="button secondary" onClick={signOut}>
          Sign out of local preview
        </button>
      </section>
      <div className="settings-grid">
        {profile && <ProfileCard profile={profile} />}
        <section className="settings-section">
          <h2>Approved preferences</h2>
          {profile?.preferences.length ? (
            <ul>
              {profile.preferences.map((p) => (
                <li key={p.id}>
                  Shorter openings · {p.language} · {p.platform}
                  <button
                    className="text-button danger"
                    disabled={busy}
                    onClick={() =>
                      void act("preference", {
                        preferenceId: p.id,
                        decision: "delete",
                      })
                    }
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p>No future writing preferences are remembered.</p>
          )}
          <Button secondary disabled={busy} onClick={reviewVoice}>
            Review my voice again
          </Button>
          <h3>Portable, with review</h3>
          <p className="helper">
            Export from your saved idea. Importing a profile creates a proposal;
            it does not silently change this workspace.
          </p>
          {state.profileSetup.approved ? (
            <button className="text-button" onClick={reviewVoice}>
              Import or compare a Personal Voice Package →
            </button>
          ) : (
            <label className="field">
              Import profile.json
              <input
                type="file"
                accept=".json,application/json"
                onChange={(e) => void importFile(e.target.files?.[0])}
              />
            </label>
          )}
        </section>
      </div>
      {state.importProposal && (
        <section className="import-proposal">
          <h2>Review imported voice</h2>
          <ProfileCard profile={state.importProposal} />
          <p className="helper">
            Only supported profile fields were read. Imported preferences need
            to be learned again in this workspace.
          </p>
          <div className="button-row">
            <Button
              disabled={busy}
              onClick={() => void act("import_decide", { approve: true })}
            >
              Approve imported profile
            </Button>
            <Button
              secondary
              disabled={busy}
              onClick={() => void act("import_decide", { approve: false })}
            >
              Discard proposal
            </Button>
          </div>
        </section>
      )}
      <section className="settings-section">
        <h2>Private on this device</h2>
        <p>
          Content is stored in a separate local database. This browser keeps a
          workspace access key and unsent editor text. Clearing browser data can
          remove your ability to reopen it here; export work you want to keep.
        </p>
        <p className="helper">
          This is local capability isolation, not a hosted account or encrypted
          cloud vault. A person with access to your OS account can access local
          files.
        </p>
        <div className="button-row">
          {state.workspace.sample ? (
            <>
              <Button secondary disabled={busy} onClick={restorePersonal}>
                Return to my private agency
              </Button>
              <Button secondary disabled={busy} onClick={startSample}>
                Start another sample
              </Button>
            </>
          ) : (
            <Button secondary disabled={busy} onClick={startSample}>
              Open a separate sample workspace
            </Button>
          )}
        </div>
      </section>
      <section className="settings-section">
        <h2>Devices & usage</h2>
        <p>
          This device only. Deterministic preview uses no model credits. Real
          agent routes remain untested; managed writing is blocked. No account,
          billing, or social connection is provisioned here.
        </p>
      </section>
    </>
  );
}

function Placeholder({ title, back }: { title: string; back: () => void }) {
  const messages: Record<string, string> = {
    Scheduling:
      "A place to plan when your work goes out. Scheduling is not enabled in this private alpha.",
    Channels:
      "A home for the channels you choose. Account connections are not enabled in this private alpha.",
    Analytics:
      "A place to learn from work you have shared. There are no live metrics or imported performance claims here.",
    Audience:
      "A place to understand the people you write for. This alpha stores your chosen audience in your private brand hub.",
  };
  return (
    <>
      <Heading eyebrow="A LITTLE FURTHER DOWN THE ROAD" title={title}>
        {messages[title]}
      </Heading>
      <div className="placeholder-art">
        <span aria-hidden="true">↗</span>
        <h2>Start with something worth sharing.</h2>
        <p>
          The founder-alpha journey is ready in Ideas: bring a source, shape two
          drafts, and save what you want to keep.
        </p>
        <Button onClick={back}>Back to Ideas →</Button>
      </div>
    </>
  );
}

function SamplePreview({
  state,
  start,
  exportPack,
}: {
  state: AlphaState;
  start: () => void;
  exportPack: () => Promise<void>;
}) {
  return (
    <>
      <Heading
        eyebrow="FICTIONAL SAMPLE / NO ACCOUNT OR TRIAL"
        title="See what one idea can become."
      >
        A temporary, read-only example. No personal profile, private upload,
        external-agent access, or durable customer account is created.
      </Heading>
      <div className="sample-preview-grid">
        {state.variants.map((v) => (
          <article className="draft-card" key={v.id}>
            <div className="draft-header">
              <h2>{v.platform}</h2>
              <Tag>{v.language}</Tag>
            </div>
            <div
              className="sample-draft"
              lang={v.language === "繁體中文" ? "zh-Hant" : "en"}
            >
              {v.text}
            </div>
          </article>
        ))}
      </div>
      <div className="button-row">
        <Button onClick={start}>Set up my agency ↗</Button>
        <Button secondary onClick={() => void exportPack()}>
          Export fictional sample
        </Button>
      </div>
      <p className="helper">
        Sample state resets when the local server restarts. Personal materials
        require the local account preview first. The sample does not use a model
        or consume a trial.
      </p>
    </>
  );
}
