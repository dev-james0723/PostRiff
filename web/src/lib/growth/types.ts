export interface GrowthCatalog {
  postDoctor: boolean;
  genome: boolean;
  consented: boolean;
  routes: string[];
  allowedRoutes: string[];
  writer: string;
  writerRoute: string;
  maxHistoryPosts: number;
  checksPerDay: number;
  rewritesPerDay: number;
}
export interface Dimension {
  id: string;
  label: string;
  level: number | null;
  levelName: string;
  fixes: string[];
  calibrated: boolean;
}
export interface PostCheck {
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
    fit_winners?: {
      level: number;
      measuredPosts: number;
      basis: string;
      description: string;
      provenance: string;
    } | null;
  };
}
export interface PostRewrite {
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
  confirmed: boolean;
  requestKey: string;
  variantId?: string;
  variantRevision?: number;
  text?: string;
  platform?: string;
  language?: string;
}
