"""Synthetic metadata and scoped EXISTS only; no provider or live database."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,patch

from postriff_alpha.domain import AlphaError
from postriff_phase2.james_daily_call import DailyCallConfig
from postriff_phase2.james_agent_team import (
    PREFIX,READINESS_BINDING_COLUMNS,READINESS_MIGRATIONS,route,
)

USER='11111111-1111-4111-8111-111111111111'
WORKSPACE='22222222-2222-4222-8222-222222222222'
VALUES={
    'JAMES_AGENT_TEAM_ENABLED':'0','JAMES_AGENT_TEAM_CALL_ENABLED':'0',
    'JAMES_AGENT_TEAM_READER_TOKEN':'r'*40,'JAMES_AGENT_TEAM_OBSERVER_TOKEN':'o'*40,
    'JAMES_AGENT_TEAM_VERIFIER_TOKEN':'v'*40,
    'JAMES_DAILY_CALL_USER_ID':USER,'JAMES_DAILY_CALL_WORKSPACE_ID':WORKSPACE,
    'JAMES_DAILY_CALL_ENABLED':'1','JAMES_DAILY_CALL_OUTBOUND_ENABLED':'1',
    'JAMES_DAILY_CALL_SCHEDULED_ENABLED':'0','JAMES_DAILY_CALL_ACCEPTANCE_ENABLED':'1',
    'JAMES_DAILY_CALL_TIMEZONE':'America/Indiana/Indianapolis',
    'JAMES_DAILY_CALL_MAX_SECONDS':'120','JAMES_DAILY_CALL_DAILY_USD_MICRO':'5000000',
    'JAMES_DAILY_CALL_MONTHLY_USD_MICRO':'5000000',
    'JAMES_DAILY_CALL_GMAIL_ACCOUNT':'synthetic-james@example.invalid',
    'JAMES_DAILY_CALL_GMAIL_CONNECTION_ID':'pc_'+'a'*32,
    'JAMES_DAILY_CALL_CALENDAR_ACCOUNT':'synthetic-calendar@example.invalid',
    'JAMES_DAILY_CALL_CALENDAR_CONNECTION_ID':'pc_'+'b'*32,
}


def columns():
    tables=dict(READINESS_BINDING_COLUMNS)
    for migration in READINESS_MIGRATIONS.values():
        for table,fields in migration.items():tables[table]=tuple(sorted(set(tables.get(table,()))|set(fields)))
    return [(table,column) for table,fields in tables.items() for column in fields]


class ReadOnlyCursor:
    def __init__(self,metadata=None,profile=True,membership=True,editor=True,connections=None,error=None):
        self.metadata=columns() if metadata is None else metadata
        self.profile=profile;self.membership=membership;self.editor=editor
        self.connections=connections or {'gmail':True,'google_calendar':True}
        self.error=error;self.queries=[];self.result=None

    def __enter__(self):return self
    def __exit__(self,*args):return False

    def execute(self,sql,parameters):
        self.queries.append((sql,parameters))
        if not sql.startswith('SELECT '):raise AssertionError('Readiness attempted a mutation')
        if self.error:raise self.error
        if 'information_schema.columns' in sql:self.result=self.metadata
        elif 'public.pr_profiles' in sql:self.result=(self.profile,self.membership,self.editor)
        elif 'public.pr_connector_credentials' in sql:self.result=(self.connections[parameters[2]],)
        else:raise AssertionError('Unbounded or unknown readiness query')

    def fetchall(self):return self.result
    def fetchone(self):return self.result


def app_for(values=None,**cursor_options):
    values=dict(VALUES if values is None else values)
    cursor=ReadOnlyCursor(**cursor_options)
    db=MagicMock();db.cursor.return_value=cursor
    factory=MagicMock();factory.return_value.__enter__.return_value=db
    daily=MagicMock();daily.cfg=DailyCallConfig(values)
    service=SimpleNamespace(connection_factory=factory,james_daily_call=daily,
                            verify_session=MagicMock(),phone=MagicMock(),productivity_connectors=MagicMock())
    app=SimpleNamespace(_runtime=MagicMock(return_value=service),_token=MagicMock(),
                        _json=MagicMock(side_effect=lambda _start,_status,data,**kwargs:data))
    return app,service,db,cursor,values


def fetch(app,values,token=None,method='GET',path=None):
    token=values['JAMES_AGENT_TEAM_READER_TOKEN'] if token is None else token
    with patch.dict('os.environ',values,clear=True):
        return route(app,{'HTTP_AUTHORIZATION':'Bearer '+token},MagicMock(),method,path or PREFIX+'/readiness')


class ReadinessTests(unittest.TestCase):
    def test_reader_can_inspect_configuration_while_both_team_flags_are_off(self):
        app,service,db,cursor,values=app_for()
        result=fetch(app,values)
        self.assertEqual(result['readiness'],'blocked')
        self.assertTrue(result['configurationReady'])
        self.assertFalse(result['enabled']);self.assertFalse(result['callEnabled'])
        self.assertEqual(result['blockers'],['team_disabled','team_call_disabled'])
        self.assertEqual(result['callPolicy']['maxSeconds'],120)
        self.assertEqual(result['callPolicy']['reportCallMaxSeconds'],90)
        self.assertEqual(result['callPolicy']['dailyCapUsdMicro'],5_000_000)
        self.assertEqual((result['callPolicy']['quietStartMinute'],result['callPolicy']['quietEndMinute']),(1320,480))
        self.assertEqual((result['nativeState'],result['scheduleState'],result['callAdmissionState']),('unverified','unverified','not_evaluated'))
        self.assertEqual(result['binding']['providerIdentityState'],'unverified')
        self.assertTrue(all(x['ready'] for x in result['databaseMigrations'].values()))
        self.assertIn(('Cache-Control','private, no-store'),app._json.call_args.kwargs['extra_headers'])
        self.assertEqual(len(cursor.queries),4)
        db.commit.assert_not_called()
        service.verify_session.assert_not_called();app._token.assert_not_called()
        service.james_daily_call.call_report.assert_not_called()
        self.assertEqual(service.phone.mock_calls,[])
        self.assertEqual(service.productivity_connectors.mock_calls,[])

    def test_authentication_happens_before_runtime_and_database_without_session_fallback(self):
        for token in ('','wrong','authenticated-james-session','o'*40,'v'*40):
            app,service,_,_,values=app_for()
            with self.subTest(tokenClass=len(token)),self.assertRaises(AlphaError) as raised:
                fetch(app,values,token)
            self.assertEqual(raised.exception.status,401)
            app._runtime.assert_not_called();service.connection_factory.assert_not_called()
            service.verify_session.assert_not_called();app._token.assert_not_called()

    def test_shared_role_secret_cannot_make_observer_or_verifier_a_reader(self):
        for other in ('OBSERVER','VERIFIER'):
            values={**VALUES,'JAMES_AGENT_TEAM_'+other+'_TOKEN':VALUES['JAMES_AGENT_TEAM_READER_TOKEN']}
            app,service,_,_,values=app_for(values)
            with self.assertRaises(AlphaError):fetch(app,values)
            app._runtime.assert_not_called();service.connection_factory.assert_not_called()

    def test_missing_table_and_missing_column_have_finite_blocked_receipts(self):
        metadata=[row for row in columns() if row[0]!='pr_agent_team_audio_assets' and row!=('pr_agent_team_decisions','question_version')]
        app,_,db,_,values=app_for(metadata=metadata)
        result=fetch(app,values)
        self.assertFalse(result['configurationReady'])
        self.assertEqual(result['databaseMigrations']['092']['missingTables'],['pr_agent_team_audio_assets'])
        self.assertEqual(result['databaseMigrations']['091']['missingColumns'],['pr_agent_team_decisions.question_version'])
        self.assertIn('database_migrations_incomplete',result['blockers'])
        db.commit.assert_not_called()

    def test_missing_093_attendance_or_decision_binding_columns_blocks_readiness(self):
        metadata=[row for row in columns() if row[0]!='pr_agent_team_call_evidence' and row!=('pr_agent_team_decisions','question_sha256')]
        app,_,db,_,values=app_for(metadata=metadata)
        result=fetch(app,values)
        self.assertFalse(result['configurationReady'])
        self.assertTrue(result['databaseMigrations']['091']['ready'])
        self.assertTrue(result['databaseMigrations']['092']['ready'])
        self.assertFalse(result['databaseMigrations']['093']['ready'])
        self.assertEqual(result['databaseMigrations']['093']['missingTables'],['pr_agent_team_call_evidence'])
        self.assertEqual(result['databaseMigrations']['093']['missingColumns'],['pr_agent_team_decisions.question_sha256'])
        self.assertEqual(result['migrationCheck'],'required_tables_and_columns')
        db.commit.assert_not_called()

    def test_profile_membership_edit_permission_and_exact_connections_fail_closed(self):
        for options,field in (({'profile':False},'profileActive'),({'membership':False},'membershipActive'),
                            ({'editor':False},'membershipCanEdit'),
                            ({'connections':{'gmail':False,'google_calendar':True}},'gmailConnectionBound'),
                            ({'connections':{'gmail':True,'google_calendar':False}},'calendarConnectionBound')):
            app,_,_,_,values=app_for(**options)
            result=fetch(app,values)
            self.assertFalse(result['binding'][field]);self.assertFalse(result['configurationReady'])
            self.assertEqual(result['readiness'],'blocked')

    def test_binding_queries_use_only_configured_principal_workspace_and_selected_accounts(self):
        app,_,_,cursor,values=app_for()
        result=fetch(app,values)
        self.assertTrue(result['configurationReady'])
        self.assertEqual(cursor.queries[1][1],(USER,USER,WORKSPACE,USER,WORKSPACE))
        self.assertEqual(cursor.queries[2][1],(WORKSPACE,USER,'gmail','pc_'+'a'*32,'synthetic-james@example.invalid'))
        self.assertEqual(cursor.queries[3][1],(WORKSPACE,USER,'google_calendar','pc_'+'b'*32,'synthetic-calendar@example.invalid'))
        schema_sql,schema_args=cursor.queries[0]
        self.assertIn('LIMIT 256',schema_sql)
        self.assertTrue(set(schema_args[0])<=set(table for table,_ in columns()))
        serialized=json.dumps(result)
        for private in (USER,WORKSPACE,'synthetic-james@example.invalid','synthetic-calendar@example.invalid',
                        'pc_'+'a'*32,'pc_'+'b'*32,'r'*40,'o'*40,'v'*40):
            self.assertNotIn(private,serialized)
        for sql,_ in cursor.queries:
            for secret_column in ('access_ciphertext','refresh_ciphertext','key_id','phone_e164','account_label'):
                self.assertNotIn(secret_column,sql)

    def test_invalid_principal_cannot_fall_back_to_another_membership_or_query_other_users(self):
        app,_,_,cursor,values=app_for({**VALUES,'JAMES_DAILY_CALL_USER_ID':'invalid'})
        result=fetch(app,values)
        self.assertFalse(result['binding']['principalConfigured'])
        self.assertIn('principal_unconfigured',result['blockers'])
        self.assertEqual(len(cursor.queries),1)

    def test_missing_base_binding_columns_skip_scoped_row_queries(self):
        metadata=[row for row in columns() if row[0] not in READINESS_BINDING_COLUMNS]
        app,_,_,cursor,values=app_for(metadata=metadata)
        result=fetch(app,values)
        self.assertIn('binding_schema_incomplete',result['blockers'])
        self.assertFalse(result['binding']['profileActive'])
        self.assertEqual(len(cursor.queries),1)

    def test_database_and_runtime_errors_are_sanitized_without_private_error_text(self):
        private_error='private SQL endpoint credentials /Users/private-path'
        app,_,db,_,values=app_for(error=RuntimeError(private_error))
        result=fetch(app,values)
        self.assertFalse(result['databaseAvailable'])
        self.assertIn('database_unavailable',result['blockers'])
        self.assertNotIn(private_error,json.dumps(result));db.commit.assert_not_called()
        app._runtime.side_effect=RuntimeError(private_error)
        result=fetch(app,values)
        self.assertFalse(result['databaseAvailable'])
        self.assertNotIn(private_error,json.dumps(result))

    def test_configured_role_flags_and_valid_policy_are_not_execution_evidence(self):
        values={**VALUES,'JAMES_AGENT_TEAM_ENABLED':'1','JAMES_AGENT_TEAM_CALL_ENABLED':'1'}
        app,_,_,_,values=app_for(values)
        result=fetch(app,values)
        self.assertEqual(result['readiness'],'ready')
        self.assertEqual(result['nativeState'],'unverified')
        self.assertEqual(result['scheduleState'],'unverified')
        self.assertEqual(result['callAdmissionState'],'not_evaluated')
        app,_,_,_,values=app_for({**values,'JAMES_AGENT_TEAM_VERIFIER_TOKEN':''})
        result=fetch(app,values)
        self.assertFalse(result['roleSecretsConfigured'])
        self.assertIn('role_secrets_unconfigured',result['blockers'])
        app,_,_,_,values=app_for({**values,'JAMES_DAILY_CALL_DAILY_USD_MICRO':'0','JAMES_DAILY_CALL_MAX_SECONDS':'bad'})
        result=fetch(app,values)
        self.assertIn('cost_cap_unset',result['blockers']);self.assertIn('call_policy_invalid',result['blockers'])
        self.assertIsNone(result['callPolicy']['maxSeconds'])

    def test_feature_flag_exception_is_only_readiness_get(self):
        for method,path in (('POST',PREFIX+'/readiness'),('GET',PREFIX+'/status'),('POST',PREFIX+'/events'),
                            ('POST',PREFIX+'/decisions'),('GET',PREFIX+'/readiness/')):
            app,service,_,_,values=app_for()
            with self.assertRaises(AlphaError) as raised:fetch(app,values,method=method,path=path)
            self.assertEqual(raised.exception.code,'agent_team_disabled')
            app._runtime.assert_not_called();service.connection_factory.assert_not_called()


if __name__=='__main__':unittest.main()
