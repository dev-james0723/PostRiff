/** What hosted publishing can post to each platform today, separate from the format catalogue and granted capabilities. */
export function publishingSupport(platform: string): string {
  switch (platform) {
    case 'LinkedIn':
      return 'Profile posts, text only. Needs publish permission; check the post on LinkedIn afterwards.';
    case 'Threads':
      return 'Text or one image. Needs publish permission. No video, carousels or replies yet.';
    case 'Instagram':
      return 'One image with a caption, on a professional account. Needs publish permission. No Reels, Stories or carousels yet.';
    case 'Bluesky':
      return 'Text or one image; links stay clickable. Needs publish permission.';
    case 'Mastodon':
      return 'Text or one image on your server. Needs publish permission.';
    case 'Telegram':
      return "Text or one photo in your channel, sent by Rafii's bot. Needs the bot's permission to post.";
    case 'Discord':
      return "Text or one image in the channel you chose. Needs the bot's permission to post there.";
    case 'X':
      return 'Text or one image. Needs publish permission. X charges Rafii for every post.';
    case 'Facebook':
      return 'Text, a link or one photo on your Page. Needs publish permission.';
    case 'YouTube':
      return 'One video with a title. Needs upload permission. Until Google audits Rafii, uploads stay private.';
    case 'TikTok':
      return 'One video. Needs publish permission. Until TikTok audits Rafii, posts are private.';
    case 'Pinterest':
      return 'One image Pin on the board you choose. Needs publish permission.';
    default:
      return "Publishing isn't available here yet. Draft and export instead.";
  }
}
