"""Relationship follow-up (PRD R-REL-01/02): a light layer over the existing Inbox.

A relationship is a small workspace-owned record (a name the person chose, an optional provider-scoped contact
reference, interest, owner, next action, due time with its IANA zone, bounded notes) linked to threads the workspace
already ingested. States are changed by people; a deterministic rule may only suggest one. A due follow-up is a
reminder in Attention and the notification centre; it never contacts anyone. Replies stay on the existing Inbox path
(draft → exact preview/approval → fenced worker → provider read-back).
"""
