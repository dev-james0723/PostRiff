"""Validate adapter results at the worker boundary, independently of transports."""


def unknown(message="Provider outcome is unknown; reconcile before retry"):
    return {"state": "uncertain", "confirmed": message}


def normalize_result(result, job, reconciliation=False):
    allowed = {"uncertain", "held", "scheduled", "failed", "provider_accepted", "published", "verified"}
    if (not isinstance(result, dict) or not isinstance(result.get("state"), str) or result["state"] not in allowed
            or not isinstance(result.get("confirmed"), str)
            or not 1 <= len(result["confirmed"]) <= 2000):
        return unknown("Malformed adapter response; reconcile before retry")
    reference = result.get("reference", job.get("providerReference"))
    if reference is not None and (not isinstance(reference, str) or not 1 <= len(reference) <= 500):
        return unknown("Invalid provider reference; reconcile before retry")
    if reconciliation and result["state"] in ("scheduled", "held", "failed"):
        # A lookup failure or retry suggestion cannot prove that a prior POST did not run.
        return unknown("Reconciliation did not resolve the prior submission; manual review required")
    if result["state"] in ("published", "verified") and not reference:
        return unknown("Publication receipt is missing a provider reference")
    if result["state"] == "verified" and (not isinstance(result.get("verification"), str)
                                             or not 1 <= len(result["verification"]) <= 200):
        return unknown("Publication receipt is missing verification evidence")
    if job.get("cancelRequested") and result["state"] == "scheduled":
        return {"state": "canceled", "confirmed": "Canceled after the adapter confirmed rejection before acceptance"}
    return {key: result[key] for key in ("state", "confirmed", "reference", "verification") if key in result}
