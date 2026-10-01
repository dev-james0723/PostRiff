"""Founder Admin P1/P2 slice modules (CONTRACTS §8), loaded once per process.

Each slice registers its own activated metrics (`live_metrics.register`, `demo_metrics.register`), founder routes
(`http.register_route`) and cron stages (`founder_cron.register_stage`) at import, so slices never edit one shared
dispatch table. A slice that is not installed is skipped. A slice that fails to import is recorded by name and error
class only (never the message, which could carry a DSN or path) and stays unavailable: its routes answer 503 and its
metrics report `adapter_unavailable`, while every other slice and every P0 route keeps working.
"""
import importlib
import json
import logging

SLICES = (
    'founder_metrics_revenue',   # §8.A revenue, billing events, MRR and bridge, credits, forecasts
    'founder_metrics_ai',        # §8.B AI call events, tokens, latency, fallback, rollups, cost per useful outcome
    'founder_metrics_product',   # §8.C product taxonomy, activation, adoption, retention, time back
    'founder_risk',              # §8.C customer risk flags and saved views
    'founder_metrics_ops',       # §8.D request metrics, operational snapshots, connection and publishing health, support
    'founder_voice',             # §8.E founder voice sessions
    'founder_notifications',     # §8.E founder email/push notices and digests
    'founder_actions',           # §8.F reconcile, credits adjust, account blocks, refund intents
    'founder_ops',               # §8.H the founder's internal ops workspace (Settings → create once)
)
STATE = {'loaded': False, 'failed': {}}


def load():
    """Import every installed slice once; returns {slice: error class} for slices that failed to import."""
    if STATE['loaded']:
        return dict(STATE['failed'])
    STATE['loaded'] = True
    for name in SLICES:
        try:
            importlib.import_module('rafii_control.' + name)
        except ModuleNotFoundError as error:
            if error.name == 'rafii_control.' + name:
                continue
            STATE['failed'][name] = type(error).__name__
        except Exception as error:  # noqa: BLE001 - one broken slice must not take Control down
            STATE['failed'][name] = type(error).__name__
        if name in STATE['failed']:
            logging.getLogger('rafii_control.slices').error(json.dumps({'event': 'founder_slice_unavailable', 'slice': name, 'reason': STATE['failed'][name]}, sort_keys=True))
    return dict(STATE['failed'])
