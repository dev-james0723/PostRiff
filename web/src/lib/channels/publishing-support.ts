/** Current hosted executor scope, separate from the format catalogue and granted capabilities. */
export function publishingSupport(platform: string): string {
  switch (platform) {
    case 'LinkedIn':
      return 'Member profile · text posts. Image upload is not connected to this worker. Publish permission does not include read verification; the result may need a manual check.';
    case 'Threads':
      return 'Profile · text or one image. Requires publish scopes and app review. Video, carousel and replies are not implemented by this publishing worker.';
    case 'Instagram':
      return 'Professional account · one decoded image with caption. Requires publishing scopes and app review. Reels, Stories and carousel are not implemented by this publishing worker.';
    default:
      return 'Hosted publishing is not implemented for this destination. Draft and export only, unless a separately reviewed Assisted or Bridge operation is explicitly available.';
  }
}
