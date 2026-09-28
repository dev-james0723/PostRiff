"""Offline vector seam. No provider or pgvector dependency, no implicit model use."""
import math
from typing import Protocol
from .metrics import instant, right_allowed, source_policy_allowed


class TrendEmbeddingStore(Protocol):
    def snapshot(self, *, scope_key: str, decision_cutoff: str) -> list[dict]:
        """Return permitted versioned records, never fetch or generate embeddings."""
        ...


def cosine_similarity(left, right):
    if not left or len(left) != len(right) or any(type(x) not in (int,float) or not math.isfinite(x) for x in left+right):
        raise ValueError('invalid embedding vector')
    norm = math.sqrt(sum(x*x for x in left)*sum(x*x for x in right))
    return sum(a*b for a,b in zip(left,right))/norm if norm else None


def qualified_embedding(record, *, decision_cutoff, scope_key, cohort, qualification, source_policies=None):
    if not record or not qualification or qualification.get('state') != 'qualified' or cohort not in qualification.get('cohorts', []): return False
    if instant(qualification['available_at']) > instant(decision_cutoff): return False
    if qualification.get('revoked_at') and instant(qualification['revoked_at']) <= instant(decision_cutoff): return False
    if record['scope_key'] != scope_key or instant(record['available_at']) > instant(decision_cutoff) or instant(record['retention_until']) <= instant(decision_cutoff): return False
    if record.get('model_version') != qualification.get('model_version') or record.get('deleted'): return False
    if not record.get('provider_id') or not record.get('source_policy_version'): return False
    return all(source_policy_allowed(record, source_policies, decision_cutoff, p) for p in ('store_embeddings', 'llm_process', 'derive_metrics'))


def nearest_neighbors(records, vector, *, decision_cutoff, scope_key, cohort, qualification, limit=20, source_policies=None):
    if not 1 <= limit <= 100: raise ValueError('bounded neighbor limit required')
    results = []
    for row in records:
        if qualified_embedding(row, decision_cutoff=decision_cutoff, scope_key=scope_key, cohort=cohort, qualification=qualification, source_policies=source_policies):
            score = cosine_similarity(vector, row['vector'])
            if score is not None: results.append({'embedding_id': row['embedding_id'], 'candidate_id': row['candidate_id'], 'similarity': score})
    return sorted(results, key=lambda r: (-r['similarity'], r['candidate_id'], r['embedding_id']))[:limit]
