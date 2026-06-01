"""allCode exception hierarchy."""


class NewCliError(Exception):
    """Base exception for allCode failures."""


class ModelResponseError(NewCliError):
    """Raised when a model response cannot be used safely."""


class ModelConfigurationError(NewCliError):
    """Raised when model settings are incomplete before a request."""


class ModelAuthenticationError(NewCliError):
    """Raised when the configured model endpoint rejects credentials."""


class ToolExecutionError(NewCliError):
    """Raised when a tool execution contract is violated."""


class PolicyDeniedError(NewCliError):
    """Raised when policy rejects an action."""


class ApprovalRequiredError(NewCliError):
    """Raised when an action requires explicit approval."""


class ContextBudgetExceededError(NewCliError):
    """Raised when context cannot be compacted into the available budget."""


class PathPolicyDeniedError(NewCliError):
    """Raised when a path escapes or violates workspace policy."""
