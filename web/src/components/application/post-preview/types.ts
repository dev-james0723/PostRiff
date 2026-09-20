export interface PreviewMedia {
  id: string;
  kind: 'image' | 'video' | 'file';
  /** Object URL once the private media has loaded. */
  url?: string;
  alt: string;
  width?: number;
  height?: number;
  status: 'loading' | 'ready' | 'error';
}

export interface PreviewPost {
  /** Channel directory slug, e.g. `instagram`. */
  channel: string;
  channelName: string;
  /** The connected account exactly as the API names it: `@yourstudio`, `Your Studio`. */
  account: string;
  /** Object URL of the account's real profile picture, when the provider gave PostRiff one. */
  avatarUrl?: string;
  text: string;
  media: PreviewMedia[];
  /** When the post goes out; templates show it where the app shows a time. */
  publishAt: Date;
  timeZone: string;
}

export interface TemplateProps {
  post: PreviewPost;
  /** Phone width in CSS pixels is `393 * scale` plus the bezel. */
  scale: number;
}
