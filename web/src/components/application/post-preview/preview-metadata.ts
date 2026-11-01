/** Pure projection of an approved Pinterest manifest into safe preview fields; never guesses a destination. */
export function pinterestPreviewFields(options: Record<string, unknown> | undefined) {
  const title = typeof options?.title === 'string' ? options.title : undefined;
  const boardId = typeof options?.boardId === 'string' && /^\d{1,30}$/.test(options.boardId) ? options.boardId : undefined;
  const sectionId = typeof options?.boardSectionId === 'string' && /^\d{1,30}$/.test(options.boardSectionId) ? options.boardSectionId : undefined;
  let link: string | undefined;
  if (typeof options?.link === 'string') {
    try {
      const target = new URL(options.link);
      if (target.protocol === 'https:' && target.hostname && !target.username && !target.password) link = options.link;
    } catch { /* malformed, unsafe URL is never rendered as a visit link */ }
  }
  return { pinterestTitle: title, pinterestBoardId: boardId, pinterestSectionId: sectionId, pinterestLink: link };
}
