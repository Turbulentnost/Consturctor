"""Ported AgentConstructor desktop tools (local execution only).

Keep this package import lightweight so worker subprocesses can start without
loading the full tool registry.
"""

__all__ = ["invoke_ac_tool"]


def invoke_ac_tool(*args, **kwargs):
    from app.tools.ac.dispatch import invoke_ac_tool as _invoke_ac_tool

    return _invoke_ac_tool(*args, **kwargs)
