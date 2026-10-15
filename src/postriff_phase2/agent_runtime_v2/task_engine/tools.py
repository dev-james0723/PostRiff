"""Server-only tool bindings. Registration never adds a tool to a model scope.

Each executor must validate its persisted task binding and its own domain authority.
"""
ENGINE_TOOLS: set[str] = set()


def register_engine_tool(name: str) -> None:
    from ..tool_adapter import REGISTRY
    if name not in REGISTRY:
        raise ValueError('Register the task tool before its execution surface.')
    ENGINE_TOOLS.add(name)
