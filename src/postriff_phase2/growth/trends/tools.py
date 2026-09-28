"""Typed stored-only tools. Display permission never implies model permission."""
from copy import deepcopy
from postriff_alpha.domain import AlphaError

READS = ["trend_search", "trend_detail", "trend_receipt", "trend_examples", "trend_snapshots",
         "trend_methodology", "trend_calibration", "trend_language_patterns", "trend_genome", "trend_graph",
         "trend_saturation", "trend_whitespace", "trend_forecast", "trend_opportunities", "trend_opportunity", "trend_watches"]
SCOPES = {"research": READS,
          "content": READS + ["trend_opportunity_accept", "trend_watch_create", "trend_watch_disable", "trend_lab_check", "trend_lab_get"],
          "analytics": READS + ["trend_lab_get"]}
SEARCH = {"query": {"type": "string", "maxLength": 200},
          **{k: {"type": "string", "maxLength": 500} for k in
             ("platforms", "languages", "stages", "regions", "niches", "since", "until", "cursor", "method_bundle")},
          "limit": {"type": "integer"}, "view": {"type": "string", "enum": ["for_you", "rising", "breaking", "hot", "niche", "platforms"]}}
SEARCH['cursor']['maxLength'] = 8192


def register():
    from ...agent_runtime_v2 import contracts, tool_adapter, specialists
    from ...agent_runtime_v2.context import untrusted
    from ...coworker.runtime import ensure

    def call(ctx, fn):
        try:
            svc = ensure(ctx.service).coworker.trends
            data = fn(svc)
            return {"ok": True, "verified": True, "data": untrusted("EXTERNAL_SOURCE", data)}
        except AlphaError as exc:
            return {"ok": False, "verified": False, "code": exc.code or "source_unavailable", "message": str(exc)[:300]}

    if "trend_search" not in tool_adapter.REGISTRY:
        @tool_adapter.register(contracts.ToolSpec("trend_search", contracts.READ, "read", "Search stored, scoped trend receipts. No web/model calls. Keep observations, calculations and hypotheses separate."),
                               deepcopy(SEARCH), "Read stored trends")
        def search(ctx, args):
            return call(ctx, lambda svc: svc.list(ctx.workspace_id, ctx.token, {"limit": 5, **args}, model_visible=True))

        @tool_adapter.register(contracts.ToolSpec("trend_detail", contracts.READ, "read", "Read a stored trend and current permitted evidence. Missing coverage means unknown."),
                               {"trend_id": {"type": "string", "required": True}}, "Read trend evidence")
        def detail(ctx, args):
            return call(ctx, lambda svc: svc.get(ctx.workspace_id, ctx.token, args["trend_id"], model_visible=True))

        @tool_adapter.register(contracts.ToolSpec("trend_receipt", contracts.READ, "read", "Read the existing receipt and method; never infer a verified stage from a model narrative."),
                               {"trend_id": {"type": "string", "required": True}, "receipt_id": {"type": "string", "required": True}}, "Read trend receipt")
        def receipt(ctx, args):
            return call(ctx, lambda svc: svc.get(ctx.workspace_id, ctx.token, args["trend_id"], "receipts", args["receipt_id"], model_visible=True))

        @tool_adapter.register(contracts.ToolSpec("trend_opportunities", contracts.READ, "read", "Read stored workspace opportunities with separate fit dimensions. This creates no preference or Brand Brain memory."),
                               deepcopy(SEARCH), "Read workspace opportunities")
        def opportunities(ctx, args):
            return call(ctx, lambda svc: svc.list(ctx.workspace_id, ctx.token, {"limit": 5, **args}, kind="opportunity", model_visible=True))

        @tool_adapter.register(contracts.ToolSpec("trend_opportunity_accept", contracts.CREATE_DRAFT, "edit", "Save the user's selected opportunity angle as an Ideas source. No drafting charge, scheduling or publication. Requires explicit angle, account and goal.", idempotent=True),
                               {"opportunity_id": {"type": "string", "required": True}, "revision": {"type": "integer", "required": True},
                                "angle_id": {"type": "string", "required": True}, "channel_id": {"type": "string", "required": True},
                                "goal": {"type": "string", "maxLength": 1000, "required": True}, "idempotency_key": {"type": "string", "required": True}}, "Saved trend idea source")
        def accept(ctx, args):
            result = call(ctx, lambda svc: svc.accept(ctx.workspace_id, ctx.token, args["opportunity_id"], {k: v for k, v in args.items() if k != "opportunity_id"}))
            if result["ok"]:
                saved = result["data"]["data"]["data"]
                ctx.ledger.reference("source", saved["source_id"], "Selected trend idea")
                if not saved["existing"]:
                    ctx.ledger.changed.append({"type": "source", "id": saved["source_id"], "change": "saved selected trend idea",
                                               "expected": "saved idea source", "actual": "saved idea source", "verified": True})
            return result
    # Each extension registers independently, including after a partial registry reset.
    def add(name, schema, description, fn, *, effect=contracts.READ):
        if name not in tool_adapter.REGISTRY:
            tool_adapter.register(contracts.ToolSpec(name, effect, "read" if effect == contracts.READ else "edit", description),
                                  deepcopy(schema), description)(fn)

    identifier = {"trend_id": {"type": "string", "required": True}}
    for name, resource in (("trend_examples", "examples"), ("trend_snapshots", "snapshots"),
                           ("trend_genome", "genome"), ("trend_graph", "propagation"),
                           ("trend_saturation", "saturation"), ("trend_forecast", "forecast")):
        def read(ctx, args, resource=resource):
            return call(ctx, lambda svc: svc.get(ctx.workspace_id, ctx.token, args['trend_id'], resource, model_visible=True))
        add(name, identifier, "Read stored permitted " + resource + "; unknown and unqualified results are not measured claims.", read)
    for name, resource in (("trend_methodology", "methodology"), ("trend_calibration", "calibration"),
                           ("trend_language_patterns", "language-patterns"), ("trend_whitespace", "whitespace")):
        def stored(ctx, args, resource=resource):
            return call(ctx, lambda svc: svc.stored(ctx.workspace_id, ctx.token, resource, model_visible=True))
        add(name, {}, "Read current stored " + resource + "; no provider or paid refresh.", stored)
    add('trend_opportunity', {'opportunity_id': {'type': 'string', 'required': True}},
        'Read a current opportunity, separate fit dimensions and original options.',
        lambda ctx, args: call(ctx, lambda svc: svc.opportunity(ctx.workspace_id, ctx.token, args['opportunity_id'], model_visible=True)))
    add('trend_watches', {}, 'Read current in-app trend watches.',
        lambda ctx, args: call(ctx, lambda svc: svc.watches(ctx.workspace_id, ctx.token)))

    def changed(ctx, result, kind, identity, description):
        if result['ok']:
            ctx.ledger.reference(kind, identity, description)
            ctx.ledger.changed.append({'type': kind, 'id': identity, 'change': description,
                'expected': 'persisted', 'actual': 'persisted', 'verified': True})
        return result

    def watch(ctx, args):
        result = call(ctx, lambda svc: svc.watches(ctx.workspace_id, ctx.token,
            payload={**args, 'notification_policy': 'in_app'}))
        identity = result['data']['data']['data']['id'] if result['ok'] else None
        return changed(ctx, result, 'trend_watch', identity, 'Saved in-app trend watch')
    add('trend_watch_create', {**identifier, 'platforms': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 12, 'required': True},
        'threshold': {'type': 'string', 'enum': ['stage_change', 'coverage_change'], 'required': True},
        'idempotency_key': {'type': 'string', 'maxLength': 200, 'required': True}},
        'Create an explicitly requested in-app watch. No email, publication or provider dispatch.', watch,
        effect=contracts.MUTATE_REVERSIBLE)

    def disable(ctx, args):
        return changed(ctx, call(ctx, lambda svc: svc.watches(ctx.workspace_id, ctx.token, watch_id=args['watch_id'], delete=True,
            payload={k: v for k,v in args.items() if k != 'watch_id'})), 'trend_watch', args['watch_id'], 'Disabled trend watch')
    add('trend_watch_disable', {'watch_id': {'type': 'string', 'required': True},
        'expected_revision': {'type': 'integer', 'required': True}, 'idempotency_key': {'type': 'string', 'required': True}},
        'Disable an explicitly selected watch at its current revision.', disable, effect=contracts.MUTATE_REVERSIBLE)
    add('trend_lab_check', {**{k: {'type': 'string', 'required': True} for k in
        ('draft_id', 'opportunity_id', 'target_platform', 'idempotency_key')},
        **{k: {'type': 'integer', 'required': True} for k in ('draft_revision', 'opportunity_revision')}},
        'Explicitly check a saved draft against its current opportunity. Never edit, approve or publish the draft.',
        lambda ctx, args: call(ctx, lambda svc: svc.lab_create(ctx.workspace_id, ctx.token, args, model_visible=True)),
        effect=contracts.MUTATE_REVERSIBLE)
    add('trend_lab_get', {'run_id': {'type': 'string', 'required': True}}, 'Read a stored draft check; stale findings are unavailable.',
        lambda ctx, args: call(ctx, lambda svc: svc.stored(ctx.workspace_id, ctx.token, 'lab', args['run_id'], model_visible=True)))
    for key, names in SCOPES.items():
        specialists.extend_scope(key, names)
