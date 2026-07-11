class LLMInterrupted(Exception):
    """Raised when the user cancels the active LLM request."""


class LLMInvalidResponse(Exception):
    """Raised when a provider returns a transport-successful but unusable message."""

    def __init__(self, message: str, **diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics
