"""One-question-at-a-time intake state for the revision 14 workflows."""

from __future__ import annotations

import copy
from collections.abc import Mapping


QUESTION_ORDER: dict[str, tuple[str, ...]] = {
    "current_news": (
        "source_scope",
        "james_angle",
        "output_mode",
        "target_families",
        "template_decision",
    ),
    "video_analysis": (
        "intended_use",
        "caption_track",
        "target_language",
        "james_angle",
        "outputs",
        "template_decision",
    ),
    "article_to_motion": (
        "angle",
        "duration_seconds",
        "narration_mode",
        "target_families",
        "must_use_assets",
        "template_decision",
    ),
    "article_repurpose": (
        "james_angle",
        "target_families",
        "template_decision",
    ),
    "static_visual": (
        "james_angle",
        "target_families",
        "template_decision",
    ),
    "discoverability": (
        "james_angle",
        "target_families",
    ),
}

QUESTIONS: dict[str, dict[str, object]] = {
    "source_scope": {
        "question": "Which approved source scope should this news research use?",
        "options": [
            ("approved_source_packs", "Use enabled source packs and show coverage gaps."),
            ("exact_links_only", "Use only links supplied for this campaign."),
        ],
    },
    "james_angle": {
        "question": "What is James's real angle or question for this source?",
        "options": [
            ("supply_angle", "Supply the point of view that may be written in James's voice."),
            ("offer_prompts", "Receive neutral prompts without inventing James's belief."),
        ],
    },
    "output_mode": {
        "question": "Which news output should be prepared?",
        "options": [
            ("both", "Prepare separately reviewed rapid and considered stages."),
            ("rapid_response", "Prepare only a concise timely draft."),
            ("considered_article", "Prepare only the deeper article workflow."),
        ],
    },
    "target_families": {
        "question": "Which destination families need native outputs?",
        "options": [
            ("recommended_targets", "Use the smallest audience-fit set."),
            ("choose_targets", "Select exact target families manually."),
            ("draft_without_targets", "Keep a canonical draft without derivatives."),
        ],
    },
    "template_decision": {
        "question": "How should templates be selected?",
        "options": [
            ("decide_for_me", "Rank up to three eligible native templates."),
            ("choose_template", "Review and choose an exact template version."),
            ("no_template", "Generate without a stored template."),
        ],
    },
    "intended_use": {
        "question": "What should the video source be used for?",
        "options": [
            ("summarize_and_fact_check", "Build an attributed summary and verify claims separately."),
            ("translate", "Create a linked translation candidate."),
            ("content_derivatives", "Prepare article, social, or motion options after review."),
        ],
    },
    "caption_track": {
        "question": "Which available caption track should be used?",
        "options": [
            ("best_manual", "Prefer the requested-language manual caption."),
            ("best_available", "Use the best permitted track and disclose its source."),
            ("asr_plan", "Prepare an approval-gated ASR fallback plan."),
        ],
    },
    "target_language": {
        "question": "Which target language is required?",
        "options": [
            ("zh-Hant", "Prepare a Traditional Chinese translation candidate."),
            ("en", "Keep or produce an English-language artifact."),
            ("none", "Do not translate the transcript."),
        ],
    },
    "outputs": {
        "question": "Which reviewed outputs should follow the transcript?",
        "options": [
            ("brief_and_posts", "Prepare a canonical brief and native social drafts."),
            ("article", "Prepare a considered article."),
            ("motion_plan", "Prepare a HyperFrames motion plan only."),
        ],
    },
    "angle": {
        "question": "Which motion angle should organize the approved source?",
        "options": [
            ("concept", "Explain one clear concept."),
            ("how_to", "Show a concrete process."),
            ("narrative", "Build a short evidence-led story."),
        ],
    },
    "duration_seconds": {
        "question": "How long should the motion explainer be?",
        "options": [
            (60, "Use the default 60-second explainer."),
            (30, "Use a concise 30-second explainer."),
            (90, "Allow a considered 90-second explainer."),
        ],
    },
    "narration_mode": {
        "question": "What narration mode should the motion plan use?",
        "options": [
            ("approved_script", "Use a reviewed narration script."),
            ("generated_candidate", "Generate a narration candidate for review."),
            ("none", "Plan an unnarrated eligible motion unit."),
        ],
    },
    "must_use_assets": {
        "question": "Are there any approved must-use assets?",
        "options": [
            ("none", "Use no externally supplied asset."),
            ("select_assets", "Bind exact approved asset and rights records."),
        ],
    },
}


def _block(reason: str) -> dict[str, object]:
    return {"state": "blocked", "reason": reason, "options": []}


def next_v14_question(session: Mapping[str, object]) -> dict[str, object] | None:
    mode = session.get("mode")
    if mode not in QUESTION_ORDER:
        return _block("unsupported_v14_mode")
    if mode == "video_analysis" and not session.get("source_url"):
        return _block("source_url_required")
    if mode in {"article_to_motion", "article_repurpose", "static_visual"} and not session.get(
        "source_artifact_id"
    ):
        return _block("source_artifact_id_required")
    for slot in QUESTION_ORDER[str(mode)]:
        if slot not in session:
            definition = QUESTIONS[slot]
            options = [
                {
                    "value": value,
                    "description": description,
                    "recommended": index == 0,
                }
                for index, (value, description) in enumerate(definition["options"])
            ]
            return {
                "state": "awaiting_answer",
                "slot": slot,
                "question": definition["question"],
                "options": options,
            }
    return None


def apply_answer(
    session: Mapping[str, object], slot: str, value: object
) -> dict[str, object]:
    allowed_slots = {item for order in QUESTION_ORDER.values() for item in order}
    if slot not in allowed_slots:
        raise ValueError(f"unsupported_answer_slot:{slot}")
    updated = copy.deepcopy(dict(session))
    updated[slot] = copy.deepcopy(value)
    answer_sources = updated.setdefault("answer_sources", {})
    if not isinstance(answer_sources, dict):
        raise ValueError("answer_sources_must_be_mapping")
    answer_sources[slot] = "campaign_answer"
    return updated
