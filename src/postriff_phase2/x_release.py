"""Independent X acceptance/public gates. Configuration is never an API receipt."""


def acceptance_allowed(adapter, workspace_id):
    return bool(adapter and getattr(adapter, 'direct_acceptance_enabled', False)
                and workspace_id in getattr(adapter, 'direct_acceptance_workspaces', frozenset())
                and getattr(adapter, 'execution_enabled', True))


def connection_allowed(adapter, workspace_id):
    return bool(adapter and getattr(adapter, 'execution_enabled', True) and (
        getattr(adapter, 'public_connect_enabled', False)
        or acceptance_allowed(adapter, workspace_id)
        or (getattr(adapter, 'customer_connect_enabled', False)
            and workspace_id in getattr(adapter, 'customer_connect_workspaces', frozenset()))))


def management_allowed(adapter, workspace_id):
    return bool(connection_allowed(adapter, workspace_id) and (
        acceptance_allowed(adapter, workspace_id)
        or (getattr(adapter, 'public_connect_enabled', False)
            and getattr(adapter, 'direct_management_enabled', False))))


def publishing_allowed(adapter, workspace_id):
    return bool(management_allowed(adapter, workspace_id) and (
        acceptance_allowed(adapter, workspace_id)
        or getattr(adapter, 'publishing_release_enabled', False)))
