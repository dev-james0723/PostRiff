/** What hosted publishing can post to each platform today, separate from the format catalogue and granted capabilities. */
export function publishingSupport(platform: string): string {
  switch (platform) {
    case 'LinkedIn':
      return 'Profile posts, text only. Needs publish permission; check the post on LinkedIn afterwards.';
    case 'Threads':
      return 'Text or one image. Needs publish permission. No video, carousels or replies yet.';
    case 'Instagram':
      return 'One image with a caption, on a professional account. Needs publish permission. No Reels, Stories or carousels yet.';
    default:
      return "Publishing isn't available here yet. Draft and export instead.";
  }
}
