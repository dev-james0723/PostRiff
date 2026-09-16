# Artwork pipeline results

**Execution: procedural fixture only. Paid requests: 0. Image-model generations: 0.**

The provider-bound ArtBrief contains only allowlisted abstract themes and constant composition/palette values derived from selected approved public fields. Names, raw source text, quotations, identifiers, private/local/excluded fields and sensitive labels never enter that request. Internal field IDs, source references and profile revisions remain in workspace metadata. Hostile/private-value tests cover both the profile projection and the candidate provider request builder.

The UI displays the exact brief, explicit local-fixture consent, zero cost and a one-set/three-preview maximum. Refusal, insufficient context, simulated failure and quota expiry keep the local fallback. The set is cached by approved brief hash. Selection records the asset hash, provider/model, consent reference, source IDs, profile revision, crop and focal position; it survives refresh, sign-in and server restart. A profile change never replaces it. Download, replacement selection and deletion are available.

[Desktop selection](evidence/artwork-selection-desktop.png) and [mobile selection](evidence/artwork-mobile-detail.png) were visually inspected. The label is “A visual interpretation of your voice” / “Inspired by choices you approved”. The graph/list still projects the same approved records; artwork is not a score or a psychological diagnosis.

`OpenAIImageCandidate` implements the reviewed request/response contract with an injected, exact-authorization transport. It is not mounted in the running application. Returned provider assets would still need the decoder/private Storage lifecycle before selection. The [official Images reference](https://developers.openai.com/api/reference/resources/images) was checked for the request shape; no model availability, price, account access or retention entitlement is inferred from documentation.

Remaining live integration: finish the hosted Storage/image adapter wiring, select the approved provider/model and exact count, verify current pricing/retention, show the actual brief and cost, then obtain the first paid-request authorization. No paid consent is being requested now.
