"""Rafii NotificationService (adaptive coworker spec §14-§18; architecture lock N1-N5, E1-E2).

Domain event → deterministic planner → recipient/preference resolution → durable delivery rows → in-app, email
(professional HTML + plain text) or Web Push. Feature code never calls a provider: events are emitted inside the
domain transaction (or derived from authoritative state by `detector`), deliveries are claimed and sent by the
cron worker after commit, and a delivery failure can never roll back domain work.
"""
