-- Exact generic selector from rafii.io SHA 7e993563be9841f7f98758fb0c8c52f158ea7252.
-- Synthetic compatibility test only; never a production SQL invocation.
SELECT w.id::text,w.revision,w.state FROM public.pr_workspaces w
        
        WHERE w.state ? 'phase2' AND NOT w.state ? 'accountDeletion' AND NOT w.state ? 'accountBlock'
          AND EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(w.state#>'{phase2,jobs}','[]'::jsonb)) j
            WHERE coalesce(j->>'state','') NOT IN ('verified','failed','canceled','held')
              AND coalesce((j->>'leaseUntil')::double precision,0)<=%s
              AND coalesce((j->>'nextAt')::double precision,0)<=%s)
        ORDER BY w.id LIMIT 100 FOR UPDATE OF w SKIP LOCKED;
