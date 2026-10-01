"""Signature Series (RAFII Product Growth PRD §8, R-SER-01/02).

A series extends Evergreen instead of adding a second reshare engine: it is a campaign of ``kind: "series"`` in the
existing campaign planning state, with its own ``series`` body (audience question, goal, source references with
versions, owner, status, a bounded episode plan, claims with review dates, derivative lineage and draft references).
The campaign's goal/audience/facts are written once and never changed by series edits, so no automation is paused and
the trend context revision does not move. ``model`` is the pure logic, ``service`` the authority/revision/idempotency
layer, ``http`` the routes, ``agent_tools`` the typed tools and ``jobs`` the bounded fact-expiry sweep.
"""
