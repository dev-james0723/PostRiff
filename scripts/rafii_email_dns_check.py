"""Sender-domain deliverability health check (SPF, DKIM, DMARC) for Rafii notification email.

    python scripts/rafii_email_dns_check.py --domain notify.example.com [--dkim-selector resend] [--json out.json]

Read-only public DNS lookups through `dig` (no provider call, no email sent). Run it against the production sender
domain only with the owner's go-ahead. The checks follow Resend's domain setup: an SPF record on the sending
(sub)domain that includes amazonses.com, a DKIM TXT at <selector>._domainkey (Resend's selector is "resend"), and a
DMARC policy at _dmarc.<organisational domain> of quarantine or reject (p=none is reported as a warning).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys


def txt(name):
    if not shutil.which("dig"):
        raise RuntimeError("dig is not installed")
    out = subprocess.run(["dig", "+short", "TXT", name], capture_output=True, text=True, timeout=10).stdout
    records = []
    for line in out.splitlines():
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
        if parts:
            records.append("".join(parts))
    return records


def assess(domain, spf_records, dkim_records, dmarc_records):
    findings = []
    spf = [r for r in spf_records if r.lower().startswith("v=spf1")]
    if len(spf) != 1:
        findings.append({"check": "spf", "level": "error", "detail": f"expected exactly one SPF record on {domain}, found {len(spf)}"})
    elif "include:amazonses.com" not in spf[0].lower():
        findings.append({"check": "spf", "level": "error", "detail": "SPF does not include amazonses.com (Resend's sending infrastructure)"})
    elif not re.search(r"[~-]all\b", spf[0]):
        findings.append({"check": "spf", "level": "warning", "detail": "SPF should end with ~all or -all"})
    dkim = [r for r in dkim_records if "p=" in r]
    if not dkim:
        findings.append({"check": "dkim", "level": "error", "detail": "no DKIM public key found at the selector"})
    dmarc = [r for r in dmarc_records if r.lower().startswith("v=dmarc1")]
    if len(dmarc) != 1:
        findings.append({"check": "dmarc", "level": "error", "detail": f"expected exactly one DMARC record, found {len(dmarc)}"})
    else:
        policy = re.search(r"\bp=(\w+)", dmarc[0])
        if not policy:
            findings.append({"check": "dmarc", "level": "error", "detail": "DMARC record has no policy"})
        elif policy.group(1).lower() == "none":
            findings.append({"check": "dmarc", "level": "warning", "detail": "DMARC p=none monitors only; move to quarantine or reject once reports are clean"})
        if "rua=" not in dmarc[0]:
            findings.append({"check": "dmarc", "level": "warning", "detail": "DMARC has no rua= aggregate report address"})
    status = "error" if any(f["level"] == "error" for f in findings) else "warning" if findings else "ok"
    return {"domain": domain, "status": status, "findings": findings, "records": {"spf": spf, "dkim": len(dkim), "dmarc": dmarc}}


def organisational(domain):
    parts = domain.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else domain


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    parser.add_argument("--dkim-selector", default="resend")
    parser.add_argument("--json")
    args = parser.parse_args()
    result = assess(args.domain, txt(args.domain), txt(f"{args.dkim_selector}._domainkey.{args.domain}"), txt(f"_dmarc.{organisational(args.domain)}"))
    if args.json:
        with open(args.json, "w") as handle:
            json.dump(result, handle, indent=2)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
