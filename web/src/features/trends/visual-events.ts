/** Local UI events only. No network, content, evidence text, workspace context or identifiers. */
export function visualEvent(
  name:
    | 'trend_selected'
    | 'dna_dimension_opened'
    | 'platform_filtered'
    | 'compare_started'
    | 'timeline_metric_changed'
    | 'create_post_started'
) {
  if (typeof window !== 'undefined')
    window.dispatchEvent(new CustomEvent('rafii:trend-visual', { detail: { name } }));
}
