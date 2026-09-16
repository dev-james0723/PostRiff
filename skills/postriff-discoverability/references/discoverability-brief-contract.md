# Discoverability brief contract

## Input and identity

Create one brief for one canonical content version and a defined market/destination set. A materially changed thesis, source state, language market, product availability, business location, or destination produces a new version.

```json
{
  "discoverability_brief_id": "stable ID",
  "campaign_id": "stable campaign ID",
  "canonical_brief_version": "immutable version or hash",
  "story_version": "source/product/content revision",
  "brand_identity": "one brand id declared in the workspace BRAND.md, or personal when the workspace declares none",
  "discovery_modes": ["owned_search", "social_discovery"],
  "markets": ["HK", "US"],
  "languages": ["en", "zh-Hant"],
  "targets": ["exact target IDs"],
  "primary_audience_need": "specific question or job",
  "primary_intent": "informational | navigational | commercial | local | conversational | entertainment",
  "secondary_questions": ["evidence-backed audience questions"],
  "entity_vocabulary": [
    {
      "entity": "canonical subject",
      "relationship": "why it belongs",
      "market_terms": {"en": ["natural terms"], "zh-Hant": ["localized terms"]},
      "evidence_refs": ["source or research-signal IDs"]
    }
  ],
  "owned_content_plan": {
    "recommended_format": "article | landing_page | video_page | local_page | none",
    "working_titles": ["meaning-preserving candidates"],
    "answer_summary": "concise answer or null",
    "section_questions": ["logical reader questions"],
    "internal_link_targets": ["verified related content references"],
    "metadata_candidates": {"title": "optional", "description": "optional", "slug": "optional"},
    "structured_data_candidates": ["only types supported by visible content"],
    "locale_relationships": ["canonical/hreflang guidance or none"],
    "update_policy": "freshness/correction expectation"
  },
  "platform_hints": [
    {
      "target_id": "exact ChannelDraft target",
      "native_format_id": "youtube.video",
      "discovery_model": "search_led | recommendation_led | community_led | hybrid",
      "audience_vocabulary": ["native terms"],
      "opening_job": "what the first line/frame/title must do",
      "searchable_fields": ["current supported fields"],
      "media_alignment": "how visual/video supports the promise",
      "avoid": ["keyword stuffing or native failure risks"],
      "measurement": ["mode-appropriate metrics"]
    }
  ],
  "evidence_refs": ["source logs and research signals"],
  "assumptions": ["visible assumptions"],
  "unknowns": ["missing or unverified data"],
  "claims_not_to_strengthen": ["qualification-preservation records"],
  "baseline": {"window": "optional", "metrics": ["available first-party measures"]},
  "review_window": "duration or event boundary",
  "created_at": "ISO timestamp",
  "expires_at": "optional timestamp for volatile research",
  "validation_state": "candidate_ready | needs_data | blocked"
}
```

## Validation

`candidate_ready` requires:

- exact linkage to the canonical brief and story version;
- a specific audience need rather than an undifferentiated keyword list;
- evidence metadata for volatile terms, demand claims, trends, and competitor observations;
- separate owned-search and social-discovery reasoning;
- platform hints only for selected targets;
- native localization rather than word-for-word keyword translation;
- no change to the creator's point of view or factual qualifications;
- schema candidates supported by visible content;
- metrics and review windows appropriate to the discovery mode;
- explicit unknowns and no ranking, popularity, citation, or virality guarantee.

Return `needs_data` when useful research or first-party baseline data is absent but safe recommendations remain possible. Return `blocked` when the canonical brief is ungrounded, the destination is unknown, a high-risk claim lacks admissible evidence, a proposed schema would be false, or the requested tactic requires deceptive engagement or unauthorized access.

## Version and approval behavior

Changing a discoverability hint does not authorize editing or publishing the affected destination. If the change alters final copy, title, description, visible media text, link, schema, or audience, regenerate the affected artifact/version and return it to the suite's existing review and approval pipeline.

