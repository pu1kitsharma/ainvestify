"""Opt-in local agent runtime. No delivery integration or network transport."""
from .loop import AgentRuntime, Budget, Role, ROLES, validate_endpoint

__all__ = ['AgentRuntime', 'Budget', 'Role', 'ROLES', 'validate_endpoint']
