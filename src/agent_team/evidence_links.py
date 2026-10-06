"""Finite public links for a root-registered commit and signed-worker metadata.

This is a pure privacy/scope helper, not signature authentication, fetching,
publication verification, deployment readiness or authority to publish. The
caller authenticates the worker and supplies this exact approved policy.
Defaults contain no Depot/Vercel registrations. No logs URL is inferred.
Returned {url, sha} is compatible with an existing Event('git') payload.
"""

from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from .events import safe_url

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")


@dataclass(frozen=True)
class DepotRunLink:
    org_id: str
    run_id: str
    url: str


@dataclass(frozen=True)
class VercelDeploymentLinks:
    hostname: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceLinkPolicy:
    github_owner: str
    github_repository: str
    commit_sha: str
    depot_runs: tuple[DepotRunLink, ...] = ()
    vercel_deployments: tuple[VercelDeploymentLinks, ...] = ()

    def validate(self):
        if (not isinstance(self.github_owner, str) or not _OWNER.fullmatch(self.github_owner)
                or not isinstance(self.github_repository, str) or not _REPO.fullmatch(self.github_repository)
                or self.github_repository in {".", ".."}
                or not isinstance(self.commit_sha, str) or not _SHA.fullmatch(self.commit_sha)
                or not isinstance(self.depot_runs, tuple) or len(self.depot_runs) > 16
                or not isinstance(self.vercel_deployments, tuple) or len(self.vercel_deployments) > 16):
            raise ValueError("evidence_link_policy_invalid")
        depot_keys = set()
        for item in self.depot_runs:
            if (not isinstance(item, DepotRunLink) or not isinstance(item.org_id, str) or not _ID.fullmatch(item.org_id)
                    or not isinstance(item.run_id, str) or not _ID.fullmatch(item.run_id)
                    or (item.org_id, item.run_id) in depot_keys):
                raise ValueError("depot_link_registration_invalid")
            url = safe_url(item.url)
            parsed = urlsplit(url)
            if (url != item.url or not (parsed.hostname == "depot.dev" or parsed.hostname.endswith(".depot.dev"))
                    or item.org_id not in parsed.path.split("/") or item.run_id not in parsed.path.split("/")):
                raise ValueError("depot_link_registration_invalid")
            depot_keys.add((item.org_id, item.run_id))
        hosts = set()
        for item in self.vercel_deployments:
            if (not isinstance(item, VercelDeploymentLinks) or not isinstance(item.hostname, str)
                    or item.hostname in hosts or not item.hostname.endswith(".vercel.app")
                    or not isinstance(item.paths, tuple) or not 1 <= len(item.paths) <= 16
                    or any(not isinstance(path, str) for path in item.paths)
                    or len(set(item.paths)) != len(item.paths)):
                raise ValueError("vercel_link_registration_invalid")
            for path in item.paths:
                if (not isinstance(path, str) or not path.startswith("/") or len(path) > 1_024
                        or "?" in path or "#" in path
                        or safe_url("https://" + item.hostname + path) != "https://" + item.hostname + path):
                    raise ValueError("vercel_link_registration_invalid")
            hosts.add(item.hostname)
        return self


def _sha(policy, sha):
    if not isinstance(policy, EvidenceLinkPolicy):
        raise ValueError("evidence_link_policy_invalid")
    policy.validate()
    if not isinstance(sha, str) or not _SHA.fullmatch(sha) or sha != policy.commit_sha:
        raise ValueError("worker_commit_not_registered")


def github_commit_link(policy: EvidenceLinkPolicy, *, owner: str, repository: str, sha: str) -> dict:
    """Known GitHub commit route; exact owner/repo and root-provided SHA only."""
    _sha(policy, sha)
    if owner != policy.github_owner or repository != policy.github_repository:
        raise ValueError("github_repository_not_registered")
    return {"url": safe_url("https://github.com/" + owner + "/" + repository + "/commit/" + sha), "sha": sha}


def depot_run_link(policy: EvidenceLinkPolicy, *, org_id: str, run_id: str, url: str, sha: str) -> dict:
    """Only an existing exact registered URL, never an inferred Depot route."""
    _sha(policy, sha)
    safe = safe_url(url)
    matches = [item for item in policy.depot_runs if item.org_id == org_id and item.run_id == run_id and item.url == safe]
    if len(matches) != 1:
        raise ValueError("depot_run_not_registered")
    return {"url": safe, "sha": sha}


def vercel_deployment_link(policy: EvidenceLinkPolicy, *, url: str, sha: str) -> dict:
    """Only exact root-provided deployment hostname and approved paths."""
    _sha(policy, sha)
    safe = safe_url(url)
    parsed = urlsplit(safe)
    matches = [item for item in policy.vercel_deployments
               if parsed.hostname == item.hostname and (parsed.path or "/") in item.paths]
    if len(matches) != 1:
        raise ValueError("vercel_deployment_not_registered")
    return {"url": safe, "sha": sha}
