export type Mode = "personal" | "niche" | "business" | "hybrid";
export type Platform = "LinkedIn" | "Instagram" | "Threads";
export type Language = "English" | "繁體中文";
export type Tone = "warm" | "direct" | "reflective";
export interface Profile {
  tone: Tone;
  writingExample: string;
  observations: string[];
  unknowns: string[];
  fields?: ProfileField[];
  preferences: {
    id: string;
    platform: Platform;
    language: Language;
    key: string;
    value: boolean;
  }[];
}
export interface Source {
  id: string;
  kind: string;
  title: string;
  text: string;
  active: boolean;
  visibility: string;
  reviewedAt?: string;
  facts: {
    id: string;
    text: string;
    approved: boolean;
    sourceId: string;
    locator: string;
  }[];
  unknowns: string[];
}
export interface Variant {
  id: string;
  platform: Platform;
  language: Language;
  text: string;
  revision: number;
  voiceRevision: number;
  briefRevision: number;
  sourceIds: string[];
  warnings: string[];
  unknowns: string[];
  openings: string[];
  selectedOpening: number;
  customized: boolean;
  needsReview: boolean;
  blockedByRetraction: boolean;
  contentTypeId?: string;
  contentTypeVersion?: string;
  formatId?: string | null;
  contentSkillRouteIds?: string[];
  proposedUpdate?: {
    text: string;
    voiceRevision: number;
    briefRevision: number;
  } | null;
}
export interface Preference {
  id: string;
  variantId: string;
  label: string;
  platform: Platform;
  language: Language;
  status:
    | "proposed"
    | "remembered"
    | "post-only"
    | "rejected"
    | "undone"
    | "deleted";
}
export interface Route {
  id: string;
  label: string;
  status: string;
  version?: string;
  detail: string;
}
export interface Template {
  id: string;
  version: string;
  name: string;
  description: string;
  dependencies: string[];
  instructions: string[];
  example: string;
  configurationSchema: Record<
    string,
    { type: string; values?: string[]; default: unknown }
  >;
}
export interface ProfileQuestion {
  key: string;
  question: string;
  section?: string;
  hint?: string;
  options?: string[];
  multiple?: boolean;
  modes?: string[];
}
export interface ProfileField {
  id: string;
  key: string;
  section: string;
  label: string;
  value: string;
  evidence: string;
  reportedEvidence?: string;
  privacy: string;
  sourceIds: string[];
  confidence: string;
  decision: string;
  selfDescribed: boolean;
}
export interface ProfileSetup {
  schema: string;
  stage: string;
  relationshipIndex: number;
  guideIndex: number;
  history: unknown[];
  relationship: Record<string, string | string[]>;
  guidedAnswers: Record<string, string>;
  transfer: string;
  scope: Record<string, unknown> | null;
  request: {
    manifest: Record<string, unknown>;
    sha256: string;
    prompt: string;
    execution: string;
  } | null;
  candidate: ProfileField[];
  importReport: {
    state: string;
    excludedCategories: string[];
    instructions: string;
    actualSourceAccess: string;
  } | null;
  inspection:
    | {
        id: string;
        label: string;
        detection: string;
        version: string | null;
        versionSupport: string;
        authentication: string;
        sourceAccess: string;
        execution: string;
        import: string;
      }[]
    | null;
  job: { state: string; reason: string; sourceAccess: string } | null;
  approved: boolean;
}
export interface ProfileMetadata {
  relationship: ProfileQuestion[];
  guided: ProfileQuestion[];
  privacy: string[];
  evidence: string[];
}
export interface AlphaState {
  phase3?: import("./runtime-state").RuntimeState;
  phase2?: import("./phase2-types").Phase2;
  contentTypes?: import("./content-type-types").ContentTypesProjection;
  you?: {
    identitySentence: string;
    artFieldIds: string[];
    artwork: {
      state: string;
      variant: number;
      profileRevisionId?: number;
      assetHash?: string;
      selectedAt?: string;
    } | null;
    events: { action: string; at: string; profileRevision: number }[];
  };
  profileVisuals?: {
    center: { id: string; label: string; revision: number | null };
    groups: { id: string; label: string; nodes: GraphNode[] }[];
    nodes: GraphNode[];
    edges: { source_node_id: string; target_node_id: string }[];
    artBrief: {
      status: string;
      themes: string[];
      sourceFieldIds: string[];
      hash: string;
      [key: string]: unknown;
    };
    artworkSvg: string;
    assetHash: string;
    artEligibleFields: { id: string; label: string }[];
    storageBytes: number;
    approvedAt: string | null;
    needsReview: number;
    unknown: number;
  };
  schemaVersion: number;
  workspace: { id: string; name: string; sample: boolean; visibility: string };
  session: {
    id: string;
    step: number;
    answers: Record<string, unknown>;
    completed: boolean;
    answerRecords: unknown[];
  };
  brandHub: {
    id: string;
    mode: Mode | "";
    purpose: string;
    audience: string;
    subject: string;
    layers: string[];
    speaker: string;
  };
  speaker: {
    id: string;
    label: string;
    activeRevision: number | null;
    provisional: Profile | null;
    revisions: { revision: number; profile: Profile; reason: string }[];
  };
  sources: Source[];
  brief: { id: string; idea: string; revision: number; sourceIds: string[] };
  variants: Variant[];
  preferences: Preference[];
  runs: {
    id: string;
    status: string;
    failure?: string;
    message?: string;
    adapter: string;
    adapterVersion: string;
    voiceRevision: number;
    briefRevision: number;
  }[];
  runtime: { selected: string | null; routes: Route[] };
  skillInstances: {
    templateId: string;
    templateVersion: string;
    overrides: Record<string, string | boolean>;
  }[];
  savedAt: string | null;
  importProposal: Profile | null;
  research: {
    phase0: string;
    customerValidation: boolean;
    pendingParticipants: string[];
  };
  profileSetup: ProfileSetup;
  account?: {
    userId: string;
    displayName: string;
    gateway: string;
    status: string;
    productionAccount: boolean;
    methodsPreviewed: string[];
  } | null;
  membership?: {
    userId: string;
    workspaceId: string;
    role: string;
    status: string;
  } | null;
  device?: {
    id: string;
    workspaceId: string;
    status: string;
    runtimeAccess: string;
  } | null;
  socialConnections?: unknown[];
  trial?: null;
}
export interface GraphNode {
  id: string;
  category: string;
  label: string;
  short_description: string;
  evidence_state: string;
  privacy_state: string;
  source_ids: string[];
  approved_at: string | null;
  profile_revision_id: number;
}
export interface Snapshot {
  runtimeResult?: Record<string,unknown>;
  revision: number;
  state: AlphaState;
}
export interface Access {
  workspaceId: string;
  token: string;
  authMode?: "supabase";
}
export interface Created extends Snapshot, Access {}
