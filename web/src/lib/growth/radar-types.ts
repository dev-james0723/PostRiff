export interface RadarEvidence {
  id: string; source: string; url: string; title: string; excerpt: string;
  author: string; publishedAt: number | null; metrics: Record<string, number>; coverage: string;
}
export interface RadarOpportunity {
  id: string; title: string; score: number; confidence: string; confidenceReasons: string[];
  stage: string; whyNow: string; forYou: boolean; genomeReasons: { id?: string; text: string }[];
  angle: string; eligible: boolean; evidence: RadarEvidence[]; dismissed?: boolean; sourceId?: string;
}
export interface RadarScan {
  id: string; status: string; query: string; mode: 'quick' | 'deep'; sources: string[];
  useAi: boolean; maximumUsdMicro: number; maximumCredits?: number; customerCharge: string;
  chargedCredits?: number | null; refundReason?: string; notice?: string; retryAfter?: number; stale?: boolean;
  opportunities: RadarOpportunity[]; nativeReferences?: RadarEvidence[]; notification: boolean;
  sourceResults: { source: string; status: string; items: number }[];
  steps: { id: string; status: string }[]; usage: { costsVisible?: boolean; knownUsdMicro: number; actualUsdMicro: number | null; unknownAttempts: number };
}
export interface RadarCatalog {
  sources: { id: string; name: string; status: string; note?: string }[];
  consent: { sources?: string[]; ai?: boolean };
  monitor: { enabled: boolean; query?: string; timezone?: string };
  monitoringAvailable: boolean; paidMonitoring: boolean; monitorMaximumUsdMicro: number;
}
export interface RadarRequest { mode: 'quick' | 'deep'; query: string; sources: string[]; useAi: boolean; requestKey: string }
