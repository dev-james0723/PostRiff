"""James Daily Call storage acceptance in disposable Postgres. No external egress."""
import os
import uuid
import psycopg

DSN = os.environ.get('POSTRIFF_TEST_DSN', 'host=127.0.0.1 port=55438 dbname=postgres')
ONE = '00000000-0000-0000-0000-000000000001'
FAKE_NUMBER = '+15555550123'

with psycopg.connect(DSN) as db:
    wid = db.execute("select workspace_id::text from public.pr_memberships where user_id=%s and status='active' limit 1", (ONE,)).fetchone()[0]
    columns = {r[0] for r in db.execute("select column_name from information_schema.columns where table_schema='public' and table_name='pr_james_daily_call_runs'")}
    assert 'masked_destination' in columns and 'source_ids' in columns and 'follow_ups' in columns
    assert not any(name in columns for name in ('phone_number','destination_number','raw_phone','e164'))
    call_columns = {r[0] for r in db.execute("select column_name from information_schema.columns where table_schema='public' and table_name='pr_phone_calls'")}
    assert 'destination_ref' in call_columns

    run_id = str(uuid.uuid4())
    slot = 'acceptance:postgres-jdc'
    db.execute("insert into public.pr_james_daily_call_runs(id,slot_key,user_id,workspace_id,state,origin,masked_destination,context,source_ids) "
               "values(%s,%s,%s,%s,'ready','acceptance','+1 *** *** 0123','{}'::jsonb,array['gmail:m1','gcal:e1'])",
               (run_id, slot, ONE, wid))
    try:
        db.execute("insert into public.pr_james_daily_call_runs(slot_key,user_id,workspace_id,state,origin,masked_destination) "
                   "values(%s,%s,%s,'ready','acceptance','+1 *** *** 0123')", (slot, ONE, wid))
        raise AssertionError('duplicate slot accepted')
    except psycopg.errors.UniqueViolation:
        db.rollback()

with psycopg.connect(DSN) as db:
    # Migration may store a masked destination and keyed call fingerprint/reference only. It must never store the raw E.164.
    found = db.execute("select exists(select 1 from public.pr_james_daily_call_runs where context::text like %s or summary like %s)",
                       ('%' + FAKE_NUMBER + '%', '%' + FAKE_NUMBER + '%')).fetchone()[0]
    assert found is False
    db.execute("set role authenticated")
    db.execute("select set_config('request.jwt.claim.sub',%s,false)", (ONE,))
    try:
        db.execute("select * from public.pr_james_daily_call_runs").fetchall()
        raise AssertionError('authenticated client read service-only daily-call state')
    except psycopg.errors.InsufficientPrivilege:
        db.rollback()

print('PASS James Daily Call schema, duplicate slot fence, no raw-number storage, service-only RLS')
