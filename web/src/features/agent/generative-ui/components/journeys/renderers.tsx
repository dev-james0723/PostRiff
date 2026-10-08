'use client';
/**
 * Consumer journey renderers (lane E), keyed by component name. Lane C's `library.tsx` attaches them to the specs in
 * `specs.ts` (through `core/journey-renderers.tsx`). Founder renderers live in `founder-renderers.tsx` so founder
 * components never ship in the consumer chunk. Every renderer shows bound data only and re-validates its own props.
 */
import { ComparisonSummary, CoverageNote, MetricChart, MetricTable, PostFeedback } from './analytics';
import { AutomationChangeForm, AutomationDetail, AutomationList, ConnectionHealth, RecoveryGuides, RunHistory } from './automations';
import { CalendarAgenda, ProposalList, QueueStatus, RescheduleForm, SlotCheck } from './calendar';
import { CampaignBriefEditor, CampaignBriefForm, CampaignItems, CampaignLinkDrafts, CampaignList, CampaignPlan, CampaignTimeline } from './campaigns';
import { Commentary } from './commentary';
import { DraftCompare, DraftDetail, DraftEditor, DraftEvidence, DraftList } from './drafts';
import { LibraryAssetCard, LibraryBrowser, LibraryLineage, LibrarySelectionCheck } from './library';
import { ComparisonMatrix, ResearchBrief, ResearchStatus, SavedSources } from './research';
import { TaskProgress } from './tasks';
import type { JourneyRenderers } from './types';
import { VoiceAnalyzeLocal, VoiceConsentPanel, VoiceLearningStatus, VoicePreferenceList, VoiceProfileReview, VoiceSampleImport, VoiceSourcePicker } from './voice';

export const JOURNEY_RENDERERS: JourneyRenderers = {
  Commentary,
  TaskProgress,
  DraftList,
  DraftCompare,
  DraftDetail,
  DraftEvidence,
  DraftEditor,
  CalendarAgenda,
  RescheduleForm,
  SlotCheck,
  QueueStatus,
  ProposalList,
  LibraryBrowser,
  LibraryAssetCard,
  LibraryLineage,
  LibrarySelectionCheck,
  VoiceSourcePicker,
  VoiceAnalyzeLocal,
  VoiceProfileReview,
  VoicePreferenceList,
  VoiceConsentPanel,
  VoiceLearningStatus,
  VoiceSampleImport,
  CampaignList,
  CampaignPlan,
  CampaignItems,
  CampaignTimeline,
  CampaignBriefForm,
  CampaignBriefEditor,
  CampaignLinkDrafts,
  MetricTable,
  MetricChart,
  ComparisonSummary,
  CoverageNote,
  PostFeedback,
  ResearchStatus,
  ResearchBrief,
  ComparisonMatrix,
  SavedSources,
  AutomationList,
  AutomationDetail,
  RunHistory,
  ConnectionHealth,
  RecoveryGuides,
  AutomationChangeForm,
};
