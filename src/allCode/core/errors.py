"""allCode exception hierarchy."""


class NewCliError(Exception):
    """Base exception for allCode failures."""


class ModelConfigurationError(NewCliError):
    """Raised when model settings are incomplete before a request."""


class ModelAuthenticationError(NewCliError):
    """Raised when the configured model endpoint rejects credentials."""


class PathPolicyDeniedError(NewCliError):
    """Raised when a path escapes or violates workspace policy."""
