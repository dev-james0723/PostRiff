"""App-level public connection eligibility, independent of customer grants/features.

Records are operator-owned evidence references, never a substitute for actual
ordinary-user acceptance. No customer-specific E2E row is required to start.
"""
def public_connection_review(adapter, callback):
    record = getattr(adapter, 'connection_review', {})
    required = set(adapter.capability_scopes('identity'))
    if (record.get('state') != 'approved' or record.get('audience') != 'external'
            or record.get('appId') != adapter.client_id or record.get('callbackUri') != callback
            or not isinstance(record.get('evidenceRef'), str) or not record['evidenceRef'].strip()
            or not isinstance(record.get('approvedScopes'), list)
            or not required or not required.issubset(record['approvedScopes'])
            or getattr(adapter, 'sandbox', False)):
        return False
    return True
