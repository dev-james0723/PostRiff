-- Read-only verification against an isolated database after migration 132.
-- Never execute a DDL migration or write to production as part of this test.
BEGIN;
SET TRANSACTION READ ONLY;
DO $$
DECLARE
  candidate regclass := to_regclass('public.pr_x_direct_operations');
  role_name text;
  privilege_name text;
BEGIN
  IF candidate IS NULL THEN
    RAISE EXCEPTION 'Missing pr_x_direct_operations. Apply candidate migration on an isolated DB first.';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_class
     WHERE oid = candidate AND relrowsecurity AND relforcerowsecurity
  ) THEN
    RAISE EXCEPTION 'X direct journal must enable and FORCE RLS';
  END IF;
  FOREACH privilege_name IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE'] LOOP
    IF NOT has_table_privilege('service_role', candidate, privilege_name) THEN
      RAISE EXCEPTION 'X direct journal missing service_role %', privilege_name;
    END IF;
  END LOOP;
  FOREACH privilege_name IN ARRAY ARRAY['DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
    IF has_table_privilege('service_role', candidate, privilege_name) THEN
      RAISE EXCEPTION 'X direct journal has excessive service_role %', privilege_name;
    END IF;
  END LOOP;
  FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    FOREACH privilege_name IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
      IF has_table_privilege(role_name, candidate, privilege_name) THEN
        RAISE EXCEPTION 'X direct journal grants % to % unexpectedly', privilege_name, role_name;
      END IF;
    END LOOP;
  END LOOP;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
     WHERE schemaname = 'public' AND tablename = 'pr_x_direct_operations'
       AND policyname = 'pr_x_direct_operations_runtime'
       AND 'service_role' = ANY(roles)
  ) THEN
    RAISE EXCEPTION 'X direct journal service_role RLS policy is missing';
  END IF;
END $$;
ROLLBACK;
