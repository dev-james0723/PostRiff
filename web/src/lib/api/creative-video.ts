export type CreativePlatform = 'Instagram' | 'TikTok' | 'YouTube';
export type CreativeAspect = '9:16' | '16:9' | '1:1';
export type IntelligenceLevel = 'draft' | 'balanced' | 'professional' | 'cinematic';
export type CreativeRouting = 'auto' | 'manual' | 'budget' | 'hybrid';
export type CreativePriority = 'low' | 'standard' | 'high';
export type CreativeDirectionControl = 'referenceAdherence' | 'creativeFreedom' | 'visualFidelity' |
  'characterConsistency' | 'productFidelity' | 'motionQuality' | 'brandConsistency';

export type CreativeSettings = Partial<Record<CreativeDirectionControl, CreativePriority>> & {
  level: IntelligenceLevel;
  mode: CreativeRouting;
  model?: string;
  firstFrameAssetId?: string;
  firstFrameConsent?: boolean;
  maxMilliCredits?: number;
  audio?: 'auto' | 'generated' | 'silent';
  resolution?: '720p' | '1080p';
  speed?: 'standard' | 'fast';
  reliability?: 'standard' | 'strict';
};

export interface CreativeModel {
  id: string; provider: string; label: string; available: boolean; reason?: string | null;
  aspectRatios: string[]; resolutions: string[]; audioModes: string[]; mediaKind: string;
}

export interface CreativeQuote {
  id: string | null; expiresAt: number | null; eligible: boolean; reason?: string | null;
  estimatedMilliCredits: number | null; availableMilliCredits: number | null; remainingMilliCredits: number | null;
  maximumMilliCredits: number | null; estimatedUsdMicro: number | null;
  model?: string | null; provider?: string | null; label?: string | null; level: IntelligenceLevel; mode: CreativeRouting;
  pricingVersion?: string | null; billedSeconds?: number | null; audio?: string | null; resolution?: string | null;
  mediaKind?: string | null; recommendation?: string | null; limitations?: string[];
  expectedGenerationSeconds?: number | null;
  outputProfile?: { width: number; height: number; durationMs: number; hasAudio: boolean } | null;
}

export interface CreativeQuoteReply { quote: CreativeQuote; models: CreativeModel[]; }
export interface ReferenceFrames {
  page: number; pageCount: number; totalShots: number;
  frames: { shotIndex: number; startMs: number; endMs: number; timeMs: number | null;
    width?: number; height?: number; jpeg: string | null }[];
}
export interface CreativePlan {
  scenes: { sceneId: string; label: string; estimatedMilliCredits: number | null; mediaKind: string | null; reason?: string | null }[];
  totalMilliCredits: number | null;
  unpricedScenes: number;
}

export interface CreativeProvider {
  available: boolean;
  model: string | null;
  reason?: string | null;
  models?: CreativeModel[];
}

export interface CreativeProjectSummary {
  id: string;
  title: string;
  revision: number;
  sceneCount: number;
}

export interface CreativeGeneration {
  state: 'submitting' | 'pending' | 'unknown' | 'failed' | 'completed' | 'cancelled' | 'cancelling';
  estimatedUsdMicro?: number | null;
  actualUsdMicro?: number | null;
  reason?: string | null;
  model?: string | null; provider?: string | null; mediaKind?: string | null; cancellable?: boolean;
  pricingVersion?: string | null; estimatedMilliCredits?: number | null;
  settlementState?: string | null; maxMilliCredits?: number | null; accepted?: boolean | null;
}

export interface CreativeScene {
  sceneId: string;
  purpose: string;
  direction: string;
  caption: string;
  durationMs: number;
  clipId: string | null;
  sourceMediaKind?: 'user-provided' | 'generated' | 'composed' | 'unknown' | null;
  clipOrigin?: 'library' | 'generated' | 'composed' | null;
  estimatedUsdMicro?: number | null;
  generation?: CreativeGeneration | null;
  estimatedMilliCredits?: number | null;
  sourceStartMs?: number;
  sourceEndMs?: number;
  trimStartMs?: number;
  clipDurationMs?: number | null;
  evidence?: string;
}

export interface RenderedCaption {
  startMs: number; endMs: number; caption: string;
}

export interface CreativeProject {
  id: string;
  origin?: { projectId: string; revision: number };
  title: string;
  revision: number;
  headRevision: number;
  brief: string;
  platform: CreativePlatform;
  aspectRatio: CreativeAspect;
  referenceAssetId: string | null;
  analysis: {
    durationMs: number;
    width: number;
    height: number;
    fps: number;
    hasAudio: boolean;
    captionTrack?: boolean;
    measured?: { sampleIntervalMs: number; sampledFrameCount: number; hasChangingFrames: boolean;
      embeddedCaptions?: { state: string; cues: { startMs: number; endMs: number }[] };
      audioRhythm?: { state: 'measured' | 'no_audio_track' | 'unavailable'; resolutionMs: number;
        onsetMs: number[]; medianSpacingMs: number | null } };
    overlaySignals?: { state: 'measured' | 'partial' | 'unavailable'; reason?: string; minimumWordConfidence: number;
      frames: { sceneIndex: number; timeMs: number; wordCount: number; meanConfidence: number | null;
        verticalRegion: 'upper' | 'middle' | 'lower' | null; medianWordHeightPct: number | null;
        interpretiveClues: ('question' | 'call_to_action')[] }[] };
    speechTiming?: { state: 'measured' | 'unavailable' | 'no_audio_track'; language: string;
      analyzedDurationMs: number; segments: { startMs: number; endMs: number }[]; reason?: string };
    scenes: { startMs: number; endMs: number; durationMs: number; interpretation?: string;
      measurements?: { meanRgb: number[]; meanLuma: number; meanFrameChange: number; embeddedCaptionCues?: number } }[];
    inferences?: string[];
    unavailable?: string[];
  };
  context: {
    brand: string;
    subject: string;
    purpose?: string;
    audience: string;
    tone: string;
    preferences: string[];
    voiceRevision: number | string | null;
    styleRevision?: number;
    cloudAllowed: boolean;
  };
  scenes: CreativeScene[];
  history: { revision: number; sceneCount: number }[];
  export: { assetId: string; revision: number; manifest?: {
    width: number; height: number; durationMs: number; fps: number; frameCount: number;
    hasAudio: boolean; captionTrack: boolean; scenes: RenderedCaption[];
  } } | null;
}

export interface CreateCreativeProject {
  requestId: string;
  title: string;
  brief: string;
  platform: CreativePlatform;
  aspectRatio: CreativeAspect;
  referenceAssetId: string | null;
  rightsConfirmed: boolean;
  referenceLink?: string;
  speechTimingLanguage?: 'zh' | 'en' | 'auto';
}

export type CreativeSceneEdit = { sceneId: string; retake: true } | {
  sceneId: string;
  direction: string;
  caption: string;
  durationMs: number;
  clipId?: string | null;
  clipRightsConfirmed?: true;
  trimStartMs?: number;
};

export interface CreativeVideoReply {
  project: CreativeProject;
  provider: CreativeProvider;
}

export interface CreativeVideoList {
  projects: CreativeProjectSummary[];
  provider: CreativeProvider;
}

export interface CreativePerformance {
  projectId: string;
  revision: number;
  exportAssetId: string | null;
  state: 'unrendered' | 'asset_unavailable' | 'unlinked' | 'linked';
  posts: {
    jobId: string; provider: string; providerPostId: string; verifiedAt: number;
    metrics: {
      name: string; value: number | null; unit: string; availability: string; definitionVersion: string;
      observedAt: number; periodStart: number | null; periodEnd: number | null; readOffset: string | null;
      source: 'provider_insights' | 'youtube_analytics';
    }[];
  }[];
}
