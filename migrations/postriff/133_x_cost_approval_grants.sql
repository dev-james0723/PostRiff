-- Durable approvals survive process/window/evidence rotation. Candidate only.
BEGIN;
LOCK TABLE postriff.x_cost_windows, postriff.x_cost_workspaces,
 postriff.x_cost_reservations IN ACCESS EXCLUSIVE MODE;
CREATE TABLE postriff.x_cost_grants (
 app_key text NOT NULL, approval_ref text NOT NULL,
 approval_expires_at timestamptz NOT NULL,
 limits_hash text CHECK (limits_hash ~ '^[0-9a-f]{64}$'),
 app_budget_micros bigint, workspace_budget_micros bigint,
 app_request_limit bigint, workspace_request_limit bigint, allowed_price_keys text[],
 estimated_micros bigint NOT NULL DEFAULT 0 CHECK (estimated_micros >= 0),
 request_count bigint NOT NULL DEFAULT 0 CHECK (request_count >= 0),
 PRIMARY KEY (app_key, approval_ref),
 CHECK ((limits_hash IS NULL AND app_budget_micros IS NULL AND workspace_budget_micros IS NULL
  AND app_request_limit IS NULL AND workspace_request_limit IS NULL AND allowed_price_keys IS NULL)
 OR (limits_hash IS NOT NULL AND app_budget_micros IS NOT NULL AND workspace_budget_micros IS NOT NULL
  AND app_request_limit IS NOT NULL AND workspace_request_limit IS NOT NULL AND allowed_price_keys IS NOT NULL
  AND app_budget_micros > 0 AND workspace_budget_micros > 0 AND app_request_limit > 0
  AND workspace_request_limit > 0 AND cardinality(allowed_price_keys) > 0
  AND array_position(allowed_price_keys, NULL) IS NULL))
);
CREATE TABLE postriff.x_cost_grant_workspaces (
 app_key text NOT NULL, approval_ref text NOT NULL, workspace_id text NOT NULL,
 estimated_micros bigint NOT NULL DEFAULT 0 CHECK (estimated_micros >= 0),
 request_count bigint NOT NULL DEFAULT 0 CHECK (request_count >= 0),
 PRIMARY KEY (app_key, approval_ref, workspace_id),
 FOREIGN KEY (app_key, approval_ref) REFERENCES postriff.x_cost_grants(app_key, approval_ref)
);
CREATE TABLE postriff.x_cost_price_evidence (
 app_key text NOT NULL, evidence_hash text NOT NULL CHECK (evidence_hash ~ '^[0-9a-f]{64}$'),
 evidence_ref text NOT NULL, expires_at timestamptz NOT NULL,
 unit_prices jsonb NOT NULL CHECK (jsonb_typeof(unit_prices)='object'),
 PRIMARY KEY (app_key, evidence_hash)
);
CREATE TABLE postriff.x_cost_app_activation (
 app_key text PRIMARY KEY, active_approval_ref text, active_price_evidence_hash text,
 activation_ref text, generation bigint NOT NULL DEFAULT 0 CHECK(generation >= 0),
 FOREIGN KEY (app_key, active_approval_ref) REFERENCES postriff.x_cost_grants(app_key, approval_ref),
 FOREIGN KEY (app_key, active_price_evidence_hash) REFERENCES postriff.x_cost_price_evidence(app_key, evidence_hash),
 CHECK ((active_approval_ref IS NULL AND active_price_evidence_hash IS NULL AND activation_ref IS NULL)
 OR (active_approval_ref IS NOT NULL AND active_price_evidence_hash IS NOT NULL AND activation_ref IS NOT NULL))
);
WITH r AS (
 SELECT app_key,window_id,sum(estimated_micros) cost,count(*) n
 FROM postriff.x_cost_reservations GROUP BY app_key,window_id
)
INSERT INTO postriff.x_cost_grants(app_key,approval_ref,approval_expires_at,estimated_micros,request_count)
SELECT w.app_key,w.approval_ref,min(w.approval_expires_at),
 sum(greatest(w.estimated_micros,coalesce(r.cost,0))),
 sum(greatest(w.request_count,coalesce(r.n,0)))
FROM postriff.x_cost_windows w LEFT JOIN r USING(app_key,window_id)
GROUP BY w.app_key,w.approval_ref;
WITH r AS (
 SELECT app_key,window_id,workspace_id,sum(estimated_micros) cost,count(*) n
 FROM postriff.x_cost_reservations GROUP BY app_key,window_id,workspace_id
), combined AS (
 SELECT coalesce(w.app_key,r.app_key) app_key,coalesce(w.window_id,r.window_id) window_id,
 coalesce(w.workspace_id,r.workspace_id) workspace_id,
 greatest(coalesce(w.estimated_micros,0),coalesce(r.cost,0)) cost,
 greatest(coalesce(w.request_count,0),coalesce(r.n,0)) n
 FROM postriff.x_cost_workspaces w FULL JOIN r USING(app_key,window_id,workspace_id)
)
INSERT INTO postriff.x_cost_grant_workspaces(app_key,approval_ref,workspace_id,estimated_micros,request_count)
SELECT c.app_key,w.approval_ref,c.workspace_id,sum(c.cost),sum(c.n)
FROM combined c JOIN postriff.x_cost_windows w USING(app_key,window_id)
GROUP BY c.app_key,w.approval_ref,c.workspace_id;
UPDATE postriff.x_cost_grants g SET estimated_micros=greatest(g.estimated_micros,s.cost),
 request_count=greatest(g.request_count,s.n)
FROM (SELECT app_key,approval_ref,sum(estimated_micros) cost,sum(request_count) n
 FROM postriff.x_cost_grant_workspaces GROUP BY app_key,approval_ref) s
WHERE g.app_key=s.app_key AND g.approval_ref=s.approval_ref;
INSERT INTO postriff.x_cost_app_activation(app_key) SELECT DISTINCT app_key FROM postriff.x_cost_grants;
ALTER TABLE postriff.x_cost_reservations ADD COLUMN cost_approval_ref text,
 ADD COLUMN admission_version smallint, ADD COLUMN price_evidence_hash text;
UPDATE postriff.x_cost_reservations r SET cost_approval_ref=w.approval_ref,admission_version=1
FROM postriff.x_cost_windows w WHERE r.app_key=w.app_key AND r.window_id=w.window_id;
ALTER TABLE postriff.x_cost_reservations ALTER COLUMN cost_approval_ref SET NOT NULL,
 ALTER COLUMN admission_version SET NOT NULL,
 ADD CONSTRAINT x_cost_admission_version_ck CHECK
 (admission_version=1 OR(admission_version=2 AND price_evidence_hash IS NOT NULL)),
 ADD FOREIGN KEY(app_key,cost_approval_ref) REFERENCES postriff.x_cost_grants(app_key,approval_ref),
 ADD FOREIGN KEY(app_key,price_evidence_hash) REFERENCES postriff.x_cost_price_evidence(app_key,evidence_hash);
-- No defaults: an old binary cannot bypass central approval counters.
ALTER TABLE postriff.x_cost_windows ADD CONSTRAINT x_cost_window_approval_uniq UNIQUE(app_key,window_id,approval_ref);
ALTER TABLE postriff.x_cost_reservations ADD FOREIGN KEY(app_key,window_id,cost_approval_ref)
 REFERENCES postriff.x_cost_windows(app_key,window_id,approval_ref);
ALTER TABLE postriff.x_cost_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE postriff.x_cost_grant_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE postriff.x_cost_price_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE postriff.x_cost_app_activation ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON postriff.x_cost_grants,postriff.x_cost_grant_workspaces,
 postriff.x_cost_price_evidence,postriff.x_cost_app_activation FROM PUBLIC;
DO $$
DECLARE client_role text;
BEGIN
 FOREACH client_role IN ARRAY ARRAY['anon','authenticated'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
   EXECUTE format('REVOKE ALL ON postriff.x_cost_grants,postriff.x_cost_grant_workspaces,postriff.x_cost_price_evidence,postriff.x_cost_app_activation FROM %I',client_role);
  END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
  EXECUTE 'GRANT USAGE ON SCHEMA postriff TO service_role';
  EXECUTE 'GRANT SELECT,INSERT,UPDATE ON postriff.x_cost_grants,postriff.x_cost_grant_workspaces,postriff.x_cost_app_activation TO service_role';
  EXECUTE 'GRANT SELECT,INSERT ON postriff.x_cost_price_evidence TO service_role';
 END IF;
END;
$$;
COMMIT;
