"""
Timeout configuration utilities.

Delegates to centralized settings. Kept for backward compatibility.
"""


class TimeoutConfig:
    """Timeout accessors backed by centralized settings."""

    @classmethod
    def get_websocket_keepalive_interval(cls) -> int:
        from graph_kb_api.config import settings

        return settings.websocket_keepalive_interval

    @classmethod
    def get_operation_timeout(cls) -> int:
        from graph_kb_api.config import settings

        return settings.operation_timeout

    @classmethod
    def get_ask_code_timeout(cls) -> int:
        from graph_kb_api.config import settings

        return settings.ask_code_timeout

    @classmethod
    def get_retrieval_timeout(cls) -> int:
        from graph_kb_api.config import settings

        return settings.retrieval_timeout

    @classmethod
    def get_deep_agent_timeout(cls) -> int:
        from graph_kb_api.config import settings

        return settings.deep_agent_timeout
