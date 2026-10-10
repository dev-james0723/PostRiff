/** Bounded linear comparison: highlight the changed middle while preserving exact original whitespace. */
export function compareWording(neutral: string, proposed: string) {
  const before = neutral.split(/(\s+)/u);
  const after = proposed.split(/(\s+)/u);
  let start = 0;
  while (start < before.length && start < after.length && before[start] === after[start]) start++;
  let end = 0;
  while (end < before.length - start && end < after.length - start && before[before.length - 1 - end] === after[after.length - 1 - end]) end++;
  return {
    prefix: after.slice(0, start).join(''),
    changed: after.slice(start, after.length - end).join(''),
    removed: before.slice(start, before.length - end).join(''),
    suffix: end ? after.slice(after.length - end).join('') : '',
    identical: neutral === proposed
  };
}
