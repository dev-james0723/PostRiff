# Next exact action — preserve current production baseline locally

2026-10-15 UTC. **Pending explicit approval; not executed.**

Merge observed live source **`5e4f4e13773e3739d0aa9cd1f3c57f3a23c9140e`** into local isolated branch **`codex/rafii-pinterest-production-prep-20261014`**, then resolve any scoped conflicts while preserving both Pinterest work and current account security behavior, and run cloud regression validation. The prepared command is `git merge --no-ff 5e4f4e13773e3739d0aa9cd1f3c57f3a23c9140e`. Current HEAD is `6d36716cfcc945fcc93a819ba243ffa870a1a799`, containing the independently authorized and cloud-verified quota hardening on prior2d61b536. The incoming live revision and exact isolated merge action are unchanged.

The four overlapping product files are `hosted_app.py`, `hosted_worker.py`, `web/src/lib/api/client.ts` and `web/src/lib/api/types.ts`. Incoming changes include device trust, security step-up, account holds, worker authorization fences and account-deletion cleanup. The additive Pinterest quota migration is not in the incoming revision; its separate local least-privilege fix remains preserved. This action creates only a local Git merge commit and synthetic cloud validation. It does not push, merge remotely, deploy, apply production SQL, install credentials, grant live OAuth consent or publish Pins.

Automatic approval review rejected the attempted local merge before execution, interpreting the mission's separately approved merge boundary as applying to this action. No workaround merge was performed. The exact native approval question is pending in this thread. Existing quota hardening and read-only infrastructure inspection are independent authorized work and continue.

[Fresh source/schema/billing preflight](evidence/pilot-continuation-preflight.json). Callback registration already passed and needs no repeated approval. Production release remains **NO-GO**.
