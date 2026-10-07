export type AdviceGoal = 'conversation' | 'shareability' | 'authority' | 'reach' | 'general';
export interface GrowthCatalog {
  radar?: boolean;
  postDoctor: boolean;
  postDoctorV2?: boolean;
  genome: boolean;
  consented: boolean;
  routes: string[];
  allowedRoutes: string[];
  writer: string;
  writerRoute: string;
  maxHistoryPosts: number;
  checksPerDay: number;
  rewritesPerDay: number;
  postmortem: boolean;
  audienceMiner: boolean;
  summaryRoute: string;
  audienceConsent: boolean;
}
export interface Dimension {
  id: string;
  label: string;
  level: number | null;
  levelName: string;
  fixes: string[];
  calibrated: boolean;
  missingContext?: string[];
}
export interface PostComparison {
  recommended: 'original' | 'candidate' | 'equivalent' | 'unsure';
  status: string;
  reasons: string[];
  orderChecked: boolean;
}
export interface PostCheck {
  goal?: AdviceGoal;
  contextDigest?: string;
  missingContext?: Record<string, string[]>;
  priorityActions?: {dimension: string; kind: 'context' | 'improve'; concern: string; change: string}[];
  runId: string;
  questionSet: string;
  status: string;
  dimensions: Dimension[];
  confidence: string;
  confidenceReasons: string[];
  helping: string[];
  hurting: string[];
  change: string[];
  risks: string[];
  baseline?: { measuredPosts: number; basis: string; genomeId: string | null };
  computed?: {
    creatorFit?: { dimension: string; metric: string; level: string; postCount: number; basis: string }[];
    fit_winners?: {
      level: number;
      measuredPosts: number;
      basis: string;
      description: string;
      provenance: string;
    } | null;
  };
}

export interface OutcomeMetric {
  value: number | null;
  availability: string;
  baselineCount: number;
  multiple?: number | null;
  median?: number | null;
  percentile?: number | null;
  observedAt?: number | null;
}
export interface Postmortem {
  id: string;
  jobId: string;
  horizon: '1h' | '24h' | '7d';
  title: string;
  platform: string;
  status: string;
  basisDigest: string;
  prediction: { levels: Dimension[]; contentRevision?: number } | null;
  reading: { status: string; horizon: string; metrics: Record<string, OutcomeMetric> };
  comparisons: { dimension: string; label: string; levelName: string; metric: string; outcome: OutcomeMetric; status: string }[];
  lessons: GenomeStatement[];
  notice: string;
  explanation?: { status: string; cause: string; text: string; nextStep: string };
}
export interface CalibrationVersion {
  id: string;
  status: string;
  candidates: { metric: string; postCount: number; cohort: string[]; dimensions: { id: string; holdoutSpearman: number; weight: number; trainCount: number; holdoutCount: number }[] }[];
}
export interface GrowthReadingWindow {
  horizon: '1h' | '24h' | '7d';
  available: boolean;
  state?: 'measured' | 'pending_horizon' | 'scheduled' | 'pending' | 'disabled' | 'unsupported' | 'disconnected' | 'rights_unavailable' | 'unscheduled' | 'unavailable';
  dueAt?: number | null;
  reason?: string | null;
}
export interface GrowthOverview {
  posts: { jobId: string; title: string; platform: string; at: number; hasPrediction: boolean; windows: GrowthReadingWindow[] }[];
  reports: Postmortem[];
  calibration: { versions: CalibrationVersion[]; largestCohort: number; minimumPosts: number; available: boolean; notice: string };
  coverage: { maximumPosts: number; loadedPosts: number };
  measurement?: { enabled: boolean; analyticsConnections: number };
  notice: string;
}
export interface AudienceCluster {
  id: string;
  connectionId: string;
  category: string;
  label: string;
  count: number;
  examples: { id: string; text: string }[];
  evidenceIds: string[];
  needsReplyCount: number;
  suggestion: { title: string; question: string; needsFactCheck: boolean } | null;
  sourceId?: string | null;
}
export interface AudienceInsights {
  conversion: { suggestedTopics: number; savedTopics: number; writtenTopics: number; rate: number | null; basis: string };
  clusters: AudienceCluster[];
  eligibleComments: number;
  maximumPerRun: number;
  audienceConsent: boolean;
  coverage: string;
  notice: string;
}
export interface PostRewrite {
  comparison?: PostComparison;
  runId: string;
  original: string;
  rewrite: string;
  before: PostCheck;
  after: PostCheck;
  grounding: string;
  changes: {
    id: string;
    index: number;
    before: string;
    text: string;
    dimension: string;
    usesFacts: string[];
  }[];
  missingFacts: string[];
  notes: string;
}
export interface GenomeStatement {
  id: string;
  label: string;
  text: string;
  kind: string;
  grade: 'supported' | 'limited' | 'conflicting';
  evidenceIds: string[];
  counterEvidenceIds: string[];
  metric: string | null;
  provenance: string[];
  cohort: { platform: string; language: string; format: string; connectionId: string };
}
export interface CreatorGenome {
  id: string;
  status: string;
  statements: GenomeStatement[];
  postCount: number;
  measuredPosts: number;
  suppliedMetricsPosts: number;
  causal: false;
}
export interface GenomeResponse {
  active: CreatorGenome | null;
  versions: CreatorGenome[];
  shares: { id: string; revoked: boolean }[];
  evidence: Record<
    string,
    { title: string; text: string; platform: string; providerPostId: string }
  >;
}
export interface PerformanceFeedback {
  status: string;
  reason?: string;
  notice?: string;
  prediction?: { levels: Dimension[]; contentRevision: number } | null;
  readings: {
    horizon: string;
    status: string;
    minimumBaselinePosts: number;
    metrics: Record<
      string,
      {
        value: number | null;
        availability: string;
        baselineCount: number;
        median?: number | null;
        multiple?: number | null;
        observedAt?: number | null;
        provenance?: string;
      }
    >;
  }[];
}
export interface DraftCheckBody {
  goal?: AdviceGoal;
  confirmed: boolean;
  requestKey: string;
  variantId?: string;
  variantRevision?: number;
  text?: string;
  platform?: string;
  language?: string;
}
