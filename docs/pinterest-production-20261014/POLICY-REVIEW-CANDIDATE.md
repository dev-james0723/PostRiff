# Pinterest policy/data handling review candidate

Local review preparation2026-10-17. No public policy or terms changed, no legal sign-off or provider permission inferred.

Current https://rafii.io/privacy and /terms both return200. They identify Au Hin Sing, describe encrypted connected-account tokens and user approvals, and explicitly retain draft/legal-review notices. Privacy has no dedicated Pinterest subsection; transfer mechanism and processor/region verification remain incomplete. Terms retain refund/jurisdiction placeholders. The app1615884 form points to the old policy host; propose rafii.io/privacy after content review.

## Pinterest-specific text prepared for substantive review

Rafii’s Pinterest connection uses Pinterest’s official OAuth screen and the minimum permissions needed for the enabled feature. A connected account does not establish entitlement to publish publicly. Account eligibility, Pinterest’s app access tier and Rafii’s feature gates apply. Rafii never receives your Pinterest password or session cookies. Access and refresh credentials are encrypted on the server and scoped to your Rafii workspace and provider account. Board destinations are fetched through the authorized account; a Pin preview identifies its intended account, board, content and timing. Each Pin requires explicit approval. Rafii stores the publishing intent, approval and provider identifiers needed to reconcile that intent and reports success only after provider confirmation. Optional own-Pin analytics preserves native metric definitions, reporting periods, availability and read failures. Disconnect erases local credentials and stops future authorized jobs and collection; remove consent in Pinterest account settings as well where the API provides no revoke operation. Content already published on Pinterest is not silently deleted by disconnect. Data deletion requests use Account → Privacy & data and the public privacy contact.

This text requires matching actual retention/deletion behavior and Pinterest’s permitted storage before publishing. It is not a claim that all described features are currently publicly enabled. Public release is NO-GO.

## Evidence and owner decisions still needed

- Engineering/provider review: enumerate precise fields, tables, retention triggers and purge behavior for provider identity, OAuth envelopes, approval manifests, Pin IDs/read-back, quota hashes, metric observations and audit receipts. Do not silently delete existing evidence to meet an inferred rule.
- Pinterest clarification: Guidelines’ storage exception names campaign analytics, while the product proposes organic own-Pin metrics and necessary identity/receipt retention. Obtain clear provider interpretation for the disclosed use case; user approval alone does not replace provider permission.
- Model boundary: no Pinterest API responses in writer prompts or Brand Brain; current provider-data Agent gates stay off. Customer-authored source content and generated drafts are a separate data origin. Never train/fine-tune on Pinterest Materials.
- Product/legal owner: complete actual processor/region/retention/transfer and jurisdiction/refund facts; authorize final published text. No jurisdiction, timeline or contract assurance invented here.
- Operational owner: validate account deletion/purge, retention sweeps, log redaction and emergency pause on the exact released environment.

Official sources reviewed: https://policy.pinterest.com/en/developer-guidelines and https://developers.pinterest.com/docs/getting-started/set-up-authentication-and-authorization/ . The official terms link https://developers.pinterest.com/terms/ returned its shell without substantive terms; full terms review remains unavailable.
