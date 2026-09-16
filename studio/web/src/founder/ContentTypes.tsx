import { useMemo, useState } from "react";
import type { AlphaState, Snapshot } from "./types";
import type { ContentTypeDefinition } from "./content-type-types";
import "./content-types.css";

type Act = (
  action: string,
  payload?: Record<string, unknown>,
) => Promise<Snapshot | undefined>;
const originLabel = (item: ContentTypeDefinition) =>
  item.origin === "postriff"
    ? "PostRiff"
    : item.origin === "starter_pack"
      ? item.originId === "pack.creator"
        ? "Creator starter pack"
        : "Starter pack"
      : "Your workspace";

export default function ContentTypes({
  state,
  busy,
  act,
  compact = false,
}: {
  state: AlphaState;
  busy: boolean;
  act: Act;
  compact?: boolean;
}) {
  const system = state.contentTypes;
  if (!system) return null;
  const [library, setLibrary] = useState(false),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("For you"),
    [builder, setBuilder] = useState(false),
    [path, setPath] = useState(""),
    [answer, setAnswer] = useState(""),
    [example, setExample] = useState(""),
    [manualName, setManualName] = useState(""),
    [manualPurpose, setManualPurpose] = useState(""),
    [baseType, setBaseType] = useState("postriff:teach"),
    [testIdea, setTestIdea] = useState(
      "A fictional neighborhood workshop update",
    ),
    [templateName, setTemplateName] = useState(""),
    [share, setShare] = useState(false);
  const selected = system.catalog.find(
    (item) =>
      item.id === system.selection.contentTypeId &&
      item.version === system.selection.contentTypeVersion,
  );
  const suggestions = system.suggestions.slice(0, 4);
  const visible = useMemo(
    () =>
      system.catalog.filter((item) => {
        const text = (
          item.label +
          " " +
          item.description +
          " " +
          item.recommendedFormatIds.join(" ") +
          " " +
          item.recommendedPlatformIds.join(" ")
        ).toLowerCase();
        if (query && !text.includes(query.toLowerCase())) return false;
        if (filter === "Workspace") return item.origin === "workspace";
        if (filter === "Starter packs") return item.origin === "starter_pack";
        if (filter === "Saved by me")
          return system.templates.some(
            (template) =>
              !template.archived && template.contentTypeId === item.id,
          );
        return true;
      }),
    [system.catalog, system.templates, query, filter],
  );
  async function choose(id: string, version: string, formatId?: string) {
    await act("p2_content_select", {
      contentTypeId: id,
      contentTypeVersion: version,
      formatId,
    });
    setLibrary(false);
  }
  async function startBuilder(next: string) {
    setPath(next);
    if (next === "guided")
      await act("p2_content_interview_start", { path: next });
    setBuilder(true);
  }
  async function startNonGuided() {
    if (path === "example")
      await act("p2_content_interview_start", { path, example });
    else if (path === "adapt")
      await act("p2_content_interview_start", { path, baseTypeId: baseType });
    else
      await act("p2_content_interview_start", {
        path: "manual",
        definition: { name: manualName, purpose: manualPurpose },
      });
  }
  async function answerQuestion() {
    const question = state.contentTypes?.interview;
    if (!question) return;
    await act("p2_content_interview_answer", {
      questionKey: question.questionKey,
      answer,
      finish: question.index >= 2,
    });
    setAnswer("");
  }
  return (
    <section
      className={`content-types ${compact ? "compact" : ""}`}
      aria-labelledby="content-type-title"
    >
      <div className="content-type-heading">
        <div>
          <span className="eyebrow">POST TYPE / FORMAT / DESTINATION</span>
          <h2 id="content-type-title">
            {selected ? selected.label : "Choose what you want to say"}
          </h2>
          <p>
            {selected
              ? selected.description
              : "Legacy drafts remain unclassified until you choose. Your sources and custom variants stay intact."}
          </p>
        </div>
        <div className="button-row">
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => setLibrary(true)}
          >
            Browse post types
          </button>
          <button
            className="text-button"
            disabled={busy}
            onClick={() => setBuilder(true)}
          >
            Create a type
          </button>
        </div>
      </div>
      <div className="content-type-controls">
        <label className="field">
          Format
          <select
            value={system.selection.formatId || ""}
            onChange={(event) =>
              void act("p2_content_format", { formatId: event.target.value })
            }
          >
            <option value="" disabled>
              Choose a format
            </option>
            {system.formats.map((format) => (
              <option key={format.id} value={format.id}>
                {format.label}
              </option>
            ))}
          </select>
        </label>
        <p className="helper">
          Format changes independently. Destination variants are chosen later.
        </p>
      </div>
      {system.preflight.length > 0 && (
        <div className="type-preflight" aria-label="Content type preflight">
          {system.preflight.map((item) => (
            <p key={item.ruleId}>
              <strong>{item.severity}</strong> · {item.message}
            </p>
          ))}
        </div>
      )}
      {!compact && (
        <>
          <div className="suggestion-row">
            <div className="suggestion-label">
              <strong>For you</strong>
              <span>Up to four, based on this workspace.</span>
            </div>
            {suggestions.map((suggestion) => (
              <button
                key={suggestion.contentTypeId}
                disabled={busy}
                aria-describedby={`reason-${suggestion.contentTypeId}`}
                onClick={() =>
                  void choose(suggestion.contentTypeId, suggestion.version)
                }
              >
                <strong>{suggestion.label}</strong>
                <span id={`reason-${suggestion.contentTypeId}`}>
                  {suggestion.reason}
                </span>
              </button>
            ))}
          </div>
          <div className="quiet-actions">
            <label className="field">
              Starter context
              <select
                onChange={(event) =>
                  void act("p2_content_context", {
                    role: event.target.value,
                    audience: state.brandHub.audience,
                    goals: [],
                    sources: state.sources.map((source) => source.kind),
                    channels: [],
                  })
                }
                defaultValue="general"
              >
                <option value="general">General</option>
                <option value="founder">Founder</option>
                <option value="restaurant">Restaurant</option>
                <option value="realtor">Realtor</option>
                <option value="nonprofit">Nonprofit</option>
                <option value="coach">Coach</option>
                <option value="saas">SaaS</option>
                <option value="musician">Musician</option>
              </select>
            </label>
            <button
              className="text-button"
              disabled={busy}
              onClick={() => void act("p2_content_suggest")}
            >
              Refresh suggestions
            </button>
          </div>
        </>
      )}
      {system.selection.transformation && (
        <p className="type-change-note">
          Type changed from {system.selection.transformation.from}.{" "}
          {system.selection.transformation.preservedSourceIds.length} source(s)
          and {system.selection.transformation.preservedVariantIds.length}{" "}
          customized variant(s) were preserved.
        </p>
      )}
      {library && (
        <div
          className="type-library"
          role="dialog"
          aria-modal="true"
          aria-labelledby="type-library-title"
        >
          <div className="library-top">
            <div>
              <span className="eyebrow">WORKSPACE LIBRARY</span>
              <h2 id="type-library-title">Browse post types</h2>
            </div>
            <button
              className="button secondary"
              onClick={() => setLibrary(false)}
            >
              Close
            </button>
          </div>
          <div className="library-controls">
            <label className="field">
              Search
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Goal, source, format, or platform"
              />
            </label>
            {["For you", "Workspace", "Starter packs", "Saved by me"].map(
              (name) => (
                <button
                  key={name}
                  className="text-button"
                  aria-pressed={filter === name}
                  onClick={() => setFilter(name)}
                >
                  {name}
                </button>
              ),
            )}
          </div>
          <p aria-live="polite" className="helper">
            {visible.length} post type{visible.length === 1 ? "" : "s"} shown
          </p>
          <div className="type-card-grid">
            {visible.map((item) => (
              <article key={`${item.id}@${item.version}`}>
                <span className="eyebrow">
                  {originLabel(item)} · {item.version}
                </span>
                <h3>{item.label}</h3>
                <p>{item.description}</p>
                <p className="helper">
                  {item.recommendedFormatIds
                    .slice(0, 3)
                    .map(
                      (id) =>
                        system.formats.find((format) => format.id === id)
                          ?.label || id,
                    )
                    .join(" · ")}
                </p>
                <div className="button-row">
                  <button
                    className="button secondary"
                    disabled={busy}
                    onClick={() => void choose(item.id, item.version)}
                  >
                    Use this type
                  </button>
                  <details>
                    <summary>Preview structure</summary>
                    <ol>
                      {item.defaultStructure.map((section) => (
                        <li key={section}>{section}</li>
                      ))}
                    </ol>
                  </details>
                </div>
              </article>
            ))}
          </div>
          <aside className="pack-callout">
            <div>
              <strong>Creator Starter Pack</strong>
              <p>
                James’s 11-type founder baseline. Optional for every workspace.
              </p>
            </div>
            <button
              className="button secondary"
              disabled={
                busy ||
                system.installedPacks.some((pack) => pack.id === "pack.creator")
              }
              onClick={() =>
                void act("p2_content_install_pack", {
                  packId: "pack.creator",
                  version: "1.0.0",
                })
              }
            >
              {system.installedPacks.some((pack) => pack.id === "pack.creator")
                ? "Installed"
                : "Install 11 types"}
            </button>
          </aside>
        </div>
      )}
      {builder && (
        <div
          className="type-builder"
          role="dialog"
          aria-modal="true"
          aria-labelledby="type-builder-title"
        >
          <div className="library-top">
            <div>
              <span className="eyebrow">CREATE A TYPE</span>
              <h2 id="type-builder-title">Build a reusable editorial job</h2>
            </div>
            <button
              className="button secondary"
              onClick={() => {
                setBuilder(false);
                setPath("");
              }}
            >
              Close
            </button>
          </div>
          {!path && (
            <div className="builder-paths">
              <button onClick={() => void startBuilder("guided")}>
                <strong>Answer a few questions</strong>
                <span>Recommended · one question at a time</span>
              </button>
              <button onClick={() => void startBuilder("example")}>
                <strong>Use example posts</strong>
                <span>Propose a structure without copying wording</span>
              </button>
              <button onClick={() => void startBuilder("adapt")}>
                <strong>Adapt an existing type</strong>
                <span>Start from a released definition</span>
              </button>
              <button onClick={() => void startBuilder("manual")}>
                <strong>Build manually</strong>
                <span>Advanced definition controls</span>
              </button>
            </div>
          )}
          {path === "guided" && system.interview && (
            <div className="guided-question">
              <span className="eyebrow">
                QUESTION {system.interview.index + 1} OF UP TO{" "}
                {system.interview.maximum}
              </span>
              <h3>{system.interview.question}</h3>
              <textarea
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
                maxLength={1000}
              />
              <button
                className="button"
                disabled={busy || !answer.trim()}
                onClick={() => void answerQuestion()}
              >
                {system.interview.index >= 2
                  ? "Create review proposal"
                  : "Save & continue"}{" "}
                ↗
              </button>
            </div>
          )}
          {path === "example" && !system.proposal && (
            <div className="guided-question">
              <label className="field">
                Example post
                <textarea
                  value={example}
                  onChange={(event) => setExample(event.target.value)}
                  maxLength={6000}
                />
              </label>
              <button
                className="button"
                disabled={busy || !example.trim()}
                onClick={() => void startNonGuided()}
              >
                Analyze into a proposal
              </button>
            </div>
          )}
          {path === "adapt" && !system.proposal && (
            <div className="guided-question">
              <label className="field">
                Existing type
                <select
                  value={baseType}
                  onChange={(event) => setBaseType(event.target.value)}
                >
                  {system.catalog.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label} · {originLabel(item)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="button"
                disabled={busy}
                onClick={() => void startNonGuided()}
              >
                Create adaptation proposal
              </button>
            </div>
          )}
          {path === "manual" && !system.proposal && (
            <div className="guided-question">
              <label className="field">
                Name
                <input
                  value={manualName}
                  onChange={(event) => setManualName(event.target.value)}
                />
              </label>
              <label className="field">
                Purpose
                <textarea
                  value={manualPurpose}
                  onChange={(event) => setManualPurpose(event.target.value)}
                />
              </label>
              <button
                className="button"
                disabled={busy || !manualName.trim() || !manualPurpose.trim()}
                onClick={() => void startNonGuided()}
              >
                Create manual proposal
              </button>
            </div>
          )}
          {system.proposal && system.proposal.status === "needs_review" && (
            <div className="proposal-review">
              <span className="eyebrow">REVIEWABLE PROPOSAL · NOT SAVED</span>
              <label className="field">
                Name
                <input
                  defaultValue={system.proposal.name}
                  onBlur={(event) =>
                    void act("p2_content_proposal_edit", {
                      name: event.target.value,
                    })
                  }
                />
              </label>
              <label className="field">
                Purpose
                <textarea
                  defaultValue={system.proposal.purpose}
                  onBlur={(event) =>
                    void act("p2_content_proposal_edit", {
                      purpose: event.target.value,
                    })
                  }
                />
              </label>
              <label className="field">
                When not to use
                <textarea
                  defaultValue={system.proposal.whenNotToUse}
                  onBlur={(event) =>
                    void act("p2_content_proposal_edit", {
                      whenNotToUse: event.target.value,
                    })
                  }
                />
              </label>
              <h3>Structure</h3>
              <ol>
                {system.proposal.defaultStructure.map((section) => (
                  <li key={section}>{section}</li>
                ))}
              </ol>
              <h3>Synthetic examples</h3>
              <ul>
                {system.proposal.fixtureExamples.map((example) => (
                  <li key={example}>{example}</li>
                ))}
              </ul>
              <label className="field">
                Test idea
                <input
                  value={testIdea}
                  onChange={(event) => setTestIdea(event.target.value)}
                />
              </label>
              <div className="button-row">
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() =>
                    void act("p2_content_proposal_test", { idea: testIdea })
                  }
                >
                  Compare with start blank
                </button>
                <button
                  className="button"
                  disabled={busy}
                  onClick={() =>
                    void act("p2_content_proposal_save", {
                      confirmed: true,
                      proposalDigest: system.proposal!.proposalDigest,
                    })
                  }
                >
                  Confirm & save type
                </button>
              </div>
              {system.proposal.testResult && (
                <div className="test-comparison">
                  <p>
                    <strong>With type</strong>
                    <br />
                    {system.proposal.testResult.withType}
                  </p>
                  <p>
                    <strong>Start blank</strong>
                    <br />
                    {system.proposal.testResult.startBlank}
                  </p>
                </div>
              )}
            </div>
          )}
          {system.proposal?.status === "saved" && (
            <p className="proposal-saved">
              Saved to this workspace as {system.proposal.savedTypeId}. No
              generation, scheduling, or publication occurred.
            </p>
          )}
        </div>
      )}
      {selected && (
        <details className="template-save">
          <summary>Save these settings as My template</summary>
          <label className="field">
            Template name
            <input
              value={templateName}
              onChange={(event) => setTemplateName(event.target.value)}
            />
          </label>
          <label className="scope-check">
            <input
              type="checkbox"
              checked={share}
              onChange={(event) => setShare(event.target.checked)}
            />
            Share with workspace members who have access
          </label>
          <button
            className="button secondary"
            disabled={busy || !templateName.trim()}
            onClick={() =>
              void act("p2_template_create", {
                name: templateName,
                description: "Reusable settings for " + selected.label,
                contentTypeId: selected.id,
                contentTypeVersion: selected.version,
                visibility: share ? "workspace" : "private",
                overrides: { formatId: system.selection.formatId },
              })
            }
          >
            Save {share ? "workspace" : "private"} template
          </button>
          <ul>
            {system.templates
              .filter((template) => !template.archived)
              .map((template) => (
                <li key={template.id}>
                  {template.name} · {template.visibility} · revision{" "}
                  {template.revision}{" "}
                  <button
                    className="text-button"
                    onClick={() =>
                      void act("p2_template_duplicate", {
                        templateId: template.id,
                      })
                    }
                  >
                    Duplicate
                  </button>{" "}
                  <button
                    className="text-button"
                    onClick={() =>
                      void act("p2_template_archive", {
                        templateId: template.id,
                        archived: true,
                      })
                    }
                  >
                    Archive
                  </button>
                </li>
              ))}
          </ul>
        </details>
      )}
    </section>
  );
}
