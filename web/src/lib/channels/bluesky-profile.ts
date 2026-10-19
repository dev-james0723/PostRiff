export interface BlueskyProfileResponse {
  connectionId: string;
  profile: {
    did: string; handle: string; displayName: string; description: string;
    publicCounts: { followersCount?: number; followsCount?: number; postsCount?: number };
    observedAt: number; permalink: string; coverageNote: string;
  };
}
