export interface ContentFormat {
  id: string;
  version: string;
  label: string;
}
export interface ContentTypeDefinition {
  id: string;
  version: string;
  origin: "postriff" | "starter_pack" | "workspace";
  originId?: string | null;
  visibility: string;
  label: string;
  shortLabel: string;
  description: string;
  defaultStructure: string[];
  recommendedFormatIds: string[];
  recommendedPlatformIds: string[];
  requiredInputKinds: string[];
  optionalInputKinds: string[];
  skillRouteIds: string[];
  preflightRuleIds: string[];
  status: string;
}
export interface ContentSuggestion {
  contentTypeId: string;
  version: string;
  label: string;
  reason: string;
}
export interface ContentTypeProposal {
  id: string;
  path: string;
  status: string;
  name: string;
  purpose: string;
  whenToUse: string;
  whenNotToUse: string;
  requiredInputs: string[];
  optionalInputs: string[];
  defaultStructure: string[];
  recommendedFormatIds: string[];
  recommendedPlatformIds: string[];
  skillRouteIds: string[];
  preflightRuleIds: string[];
  fixtureExamples: string[];
  tested: boolean;
  testResult?: {
    execution: string;
    idea: string;
    withType: string;
    startBlank: string;
  };
  proposalDigest: string;
  savedTypeId?: string;
}
export interface PostTemplate {
  id: string;
  name: string;
  description: string;
  contentTypeId: string;
  contentTypeVersion: string;
  ownerUserId: string;
  visibility: "private" | "workspace";
  overrides: Record<string, unknown>;
  revision: number;
  archived: boolean;
}
export interface ContentTypesProjection {
  catalogVersion: string;
  formats: ContentFormat[];
  packs: {
    id: string;
    version: string;
    label: string;
    entryCount: number;
    installedByDefault: boolean;
  }[];
  catalog: ContentTypeDefinition[];
  suggestions: ContentSuggestion[];
  selection: {
    contentTypeId: string;
    contentTypeVersion: string;
    formatId: string | null;
    pillarIds: string[];
    transformation?: {
      from: string;
      to: string;
      preservedSourceIds: string[];
      preservedVariantIds: string[];
    };
  };
  interview: {
    id: string;
    path: string;
    questionKey: string;
    question: string;
    index: number;
    maximum: number;
  } | null;
  proposal: ContentTypeProposal | null;
  templates: PostTemplate[];
  preflight: {
    severity: "blocker" | "warning" | "tip";
    ruleId: string;
    message: string;
  }[];
  installedPacks: { id: string; version: string }[];
}
