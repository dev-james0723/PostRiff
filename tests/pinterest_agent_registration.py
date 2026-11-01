"""Isolated feature-on registry contract, without models or provider traffic."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from postriff_phase2 import pinterest_agent
from postriff_phase2.agent_runtime_v2 import domain_tools, tool_adapter, capability_registry, specialists, authz

domain_tools.ensure_registered()
assert 'tool.pinterest_boards' not in capability_registry.copy_table()['capabilities']
assert not capability_registry.lint()
before=set(tool_adapter.REGISTRY)  # lint first completes the runtime's lazy baseline imports
with patch.object(pinterest_agent,'enabled',return_value=True):
    pinterest_agent.register()
    pinterest_agent.register()
    domain_tools.ensure_registered()
    assert set(tool_adapter.REGISTRY)-before=={'pinterest_boards'}
    cap=capability_registry.get('tool.pinterest_boards')
    assert cap is not None and cap.risk=='R0' and cap.permission=='approve'
    assert cap.explicit_request and cap.data_grants==('connections',)
    assert cap.feature_flag=='POSTRIFF_PINTEREST_AGENT_ENABLED'
    problems=capability_registry.lint()
    assert not problems,problems
    assert capability_registry.copy_table()['capabilities']['tool.pinterest_boards']['zh-Hant']
    for scope in ('rafii_manager','content','publishing_ops'):
        assert specialists.EXTRA_SCOPES[scope].count('pinterest_boards')==1
    assert authz.EXPLICIT_REQUEST['tool.pinterest_boards']('Show my Pinterest boards')
    assert not authz.EXPLICIT_REQUEST['tool.pinterest_boards']('"Show my Pinterest boards"')
    schema=tool_adapter.REGISTRY['pinterest_boards'].schema
    assert schema['additionalProperties'] is False
    assert set(schema['properties'])=={'connectionId','boardId'}
print('PINTEREST_AGENT_REGISTRATION_PASS feature-on registry, policy, scopes, idempotent binding and current-turn authorization; no publication tool')
