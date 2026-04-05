"""
Enhanced Logger - Extended logging utilities with performance and debugging features.

This module provides an EnhancedLogger class that wraps the standard Python logger
and adds methods for memory tracking, performance timing, and structured logging.

File Logging:
    Set DEBUG_LOG_TO_FILE=true to enable writing structured JSON logs to .logs/app_debug.log.
    By default, file logging is disabled to avoid disk I/O overhead.
    Location (file:function:line) is auto-captured from the call stack.

Usage:
    from graph_kb_api.utils.enhanced_logger import EnhancedLogger

    logger = EnhancedLogger(__name__)
    logger.info("Message")  # Location auto-captured
    logger.debug("Debug", data={"key": "value"})  # With structured data
"""

import inspect
import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional

# Get project root (where .logs folder should be)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_LOGS_DIR = _PROJECT_ROOT / ".logs"


# Lazy-loaded from settings to avoid circular imports at module level
def _is_file_logging_enabled() -> bool:
    try:
        from graph_kb_api.config import settings

        return settings.debug_log_to_file
    except Exception:
        return os.environ.get("DEBUG_LOG_TO_FILE", "").lower() in ("true", "1", "yes")


def _ensure_logs_dir() -> Path:
    """Ensure .logs directory exists and return its path."""
    _LOGS_DIR.mkdir(exist_ok=True)
    return _LOGS_DIR


def _get_caller_location(stack_level: int = 2) -> str:
    """
    Get the caller's location as 'filename:function:line'.

    Args:
        stack_level: How many frames to go back (default 2 = caller of caller)

    Returns:
        Location string like 'graph_rag_service.py:retrieve_context:142'
    """
    try:
        frame = inspect.currentframe()
        for _ in range(stack_level):
            if frame is not None:
                frame = frame.f_back

        if frame is not None:
            filename = Path(frame.f_code.co_filename).name
            func_name = frame.f_code.co_name
            line_no = frame.f_lineno
            return f"{filename}:{func_name}:{line_no}"
    except Exception:
        pass
    return "unknown"


class EnhancedLogger:
    """
    Enhanced logger wrapper that extends standard logging with additional utilities.

    Provides methods for:
    - Memory tracking
    - Performance timing
    - Structured logging with extra context
    - Session/hypothesis tracking

    Usage:
        from graph_kb_api.utils.enhanced_logger import EnhancedLogger

        logger = EnhancedLogger(__name__)
        logger.info_with_memory("Starting process")
        logger.debug_with_context("Processing data", {"item_count": 100})

        with logger.timer("operation"):
            # do work
            pass
    """

    def __init__(self, name: str):
        """
        Initialize enhanced logger.

        Args:
            name: Logger name (typically __name__)
        """
        self._logger = logging.getLogger(name)
        self._session_id: Optional[str] = None
        self._hypothesis_id: Optional[str] = None

    def set_session_id(self, session_id: str) -> None:
        """Set the current session ID for all subsequent log entries."""
        self._session_id = session_id

    def set_hypothesis_id(self, hypothesis_id: str) -> None:
        """Set the current hypothesis ID for all subsequent log entries."""
        self._hypothesis_id = hypothesis_id

    def _get_memory_mb(self) -> float:
        """
        Get current process memory usage in MB.

        Returns:
            Memory usage in MB, or -1 if unavailable
        """
        try:
            # Try psutil first (more accurate, cross-platform)
            import psutil

            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            # Fallback to /proc/self/status on Linux
            try:
                with open("/proc/self/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            return int(line.split()[1]) // 1024  # KB to MB
            except (FileNotFoundError, OSError):
                pass
        return -1.0

    def _build_extra(self, **kwargs) -> Dict[str, Any]:
        """
        Build extra dict for structured logging.

        Automatically includes session_id, hypothesis_id, and memory_mb.

        Args:
            **kwargs: Additional context to include

        Returns:
            Dictionary with all context including defaults
        """
        extra = {"memory_mb": self._get_memory_mb(), **kwargs}

        if self._session_id:
            extra["sessionId"] = self._session_id

        if self._hypothesis_id:
            extra["hypothesisId"] = self._hypothesis_id

        return extra

    def _write_to_file(
        self,
        level: str,
        message: str,
        location: str = "",
        data: Optional[Dict[str, Any]] = None,
        run_id: str = "",
        stack_level: int = 3,
    ) -> None:
        """
        Write structured JSON log entry to .logs/app_debug.log.

        Only writes if DEBUG_LOG_TO_FILE environment variable is enabled.
        Location is auto-captured from the call stack if not provided.

        Args:
            level: Log level
            message: Log message
            location: Code location identifier (auto-captured if empty)
            data: Optional structured data
            run_id: Optional run identifier
            stack_level: Stack frames to skip for auto-location (default 3)
        """
        if not _is_file_logging_enabled():
            return

        # Auto-capture location if not provided
        if not location:
            location = _get_caller_location(stack_level)

        log_path = _ensure_logs_dir() / "app_debug.log"

        log_entry = {
            "id": f"log_{int(time.time() * 1000)}",
            "timestamp": int(time.time() * 1000),
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "level": level,
            "location": location,
            "message": message,
            "data": data or {},
        }

        if self._session_id:
            log_entry["sessionId"] = self._session_id
        if run_id:
            log_entry["runId"] = run_id
        if self._hypothesis_id:
            log_entry["hypothesisId"] = self._hypothesis_id

        try:
            with open(log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass  # Silently fail file writes to avoid log spam

    def debug(
        self, message: str, *args, data: Optional[Dict[str, Any]] = None, **kwargs
    ) -> None:
        """Log debug message. Writes to file if DEBUG_LOG_TO_FILE is enabled."""
        self._logger.debug(message, *args, **kwargs)
        self._write_to_file("debug", message, data=data)

    def info(
        self, message: str, *args, data: Optional[Dict[str, Any]] = None, **kwargs
    ) -> None:
        """Log info message. Writes to file if DEBUG_LOG_TO_FILE is enabled."""
        self._logger.info(message, *args, **kwargs)
        self._write_to_file("info", message, data=data)

    def warning(
        self, message: str, *args, data: Optional[Dict[str, Any]] = None, **kwargs
    ) -> None:
        """Log warning message. Writes to file if DEBUG_LOG_TO_FILE is enabled."""
        self._logger.warning(message, *args, **kwargs)
        self._write_to_file("warning", message, data=data)

    def error(
        self, message: str, *args, data: Optional[Dict[str, Any]] = None, **kwargs
    ) -> None:
        """Log error message. Writes to file if DEBUG_LOG_TO_FILE is enabled."""
        self._logger.error(message, *args, **kwargs)
        self._write_to_file("error", message, data=data)

    def critical(
        self, message: str, *args, data: Optional[Dict[str, Any]] = None, **kwargs
    ) -> None:
        """Log critical message. Writes to file if DEBUG_LOG_TO_FILE is enabled."""
        self._logger.critical(message, *args, **kwargs)
        self._write_to_file("critical", message, data=data)

    def exception(
        self, message: str, *args, data: Optional[Dict[str, Any]] = None, **kwargs
    ) -> None:
        """Log exception message with traceback. Writes to file if DEBUG_LOG_TO_FILE is enabled."""
        self._logger.exception(message, *args, **kwargs)
        self._write_to_file("error", message, data=data)

    def debug_with_context(
        self, message: str, context: Dict[str, Any], *args, **kwargs
    ) -> None:
        """
        Log debug message with structured context.

        Args:
            message: Log message
            context: Dictionary of context data
            *args: Additional positional args for logger
            **kwargs: Additional keyword args for logger
        """
        extra = self._build_extra(**context)
        self._logger.debug(message, *args, extra=extra, **kwargs)
        self._write_to_file("debug", message, data=context)

    def info_with_context(
        self, message: str, context: Dict[str, Any], *args, **kwargs
    ) -> None:
        """
        Log info message with structured context.

        Args:
            message: Log message
            context: Dictionary of context data
            *args: Additional positional args for logger
            **kwargs: Additional keyword args for logger
        """
        extra = self._build_extra(**context)
        self._logger.info(message, *args, extra=extra, **kwargs)
        self._write_to_file("info", message, data=context)

    def info_with_memory(self, message: str, *args, **kwargs) -> None:
        """
        Log info message with memory usage.

        Args:
            message: Log message
            *args: Additional positional args for logger
            **kwargs: Additional keyword args for logger
        """
        extra = self._build_extra()
        full_message = f"{message} (memory: {extra['memory_mb']:.1f} MB)"
        self._logger.info(full_message, *args, extra=extra, **kwargs)
        self._write_to_file(
            "info", full_message, data={"memory_mb": extra["memory_mb"]}
        )

    def debug_with_memory(self, message: str, *args, **kwargs) -> None:
        """
        Log debug message with memory usage.

        Args:
            message: Log message
            *args: Additional positional args for logger
            **kwargs: Additional keyword args for logger
        """
        extra = self._build_extra()
        full_message = f"{message} (memory: {extra['memory_mb']:.1f} MB)"
        self._logger.debug(full_message, *args, extra=extra, **kwargs)
        self._write_to_file(
            "debug", full_message, data={"memory_mb": extra["memory_mb"]}
        )

    @contextmanager
    def timer(self, operation_name: str, level: str = "info"):
        """
        Context manager for timing operations.

        Args:
            operation_name: Name of the operation being timed
            level: Log level ("debug", "info", "warning")

        Usage:
            with logger.timer("data_processing") as timer:
                # do work
                pass
            # Access duration: timer.elapsed_seconds or timer.elapsed_ms

        Yields:
            TimerResult: Object with elapsed_seconds and elapsed_ms properties
        """

        class TimerResult:
            def __init__(self):
                self.elapsed_seconds = 0.0
                self.elapsed_ms = 0.0

        timer_result = TimerResult()
        start_time = time.time()
        start_memory = self._get_memory_mb()

        try:
            yield timer_result
        finally:
            elapsed = time.time() - start_time
            timer_result.elapsed_seconds = elapsed
            timer_result.elapsed_ms = elapsed * 1000

            end_memory = self._get_memory_mb()
            memory_delta = (
                end_memory - start_memory if end_memory > 0 and start_memory > 0 else 0
            )

            context = {
                "operation": operation_name,
                "duration_ms": elapsed * 1000,
                "start_memory_mb": start_memory,
                "end_memory_mb": end_memory,
                "memory_delta_mb": memory_delta,
            }

            log_method = getattr(self, f"{level}_with_context")
            log_method(
                f"Operation '{operation_name}' completed in {elapsed:.3f}s", context
            )

    def log_with_location(
        self, message: str, location: str, level: str = "info", **context
    ) -> None:
        """
        Log message with explicit location and context.

        Args:
            message: Log message
            location: Location identifier (e.g., "app.py:start:begin")
            level: Log level ("debug", "info", "warning", "error")
            **context: Additional context data
        """
        context["location"] = location
        log_method = getattr(self._logger, level, self._logger.info)
        log_method(f"[{location}] {message}")
        self._write_to_file(level, message, location, context)

    def structured_log(
        self,
        location: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        level: str = "debug",
        run_id: str = "",
    ) -> None:
        """
        Log with explicit location and structured data.

        Writes to file if DEBUG_LOG_TO_FILE is enabled.

        Args:
            location: Code location identifier
            message: Human-readable log message
            data: Optional dictionary of structured data
            level: Log level ("debug", "info", "warning", "error")
            run_id: Optional run identifier
        """
        # Log to standard logger
        log_method = getattr(self._logger, level, self._logger.debug)
        log_method(f"[{location}] {message}")

        # Write to file if enabled
        self._write_to_file(level, message, location, data, run_id)


# Module-level convenience function for backward compatibility
# Uses a shared logger instance
_module_logger = EnhancedLogger("structured_log")


def structured_log(
    location: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    level: str = "debug",
    session_id: str = "",
    run_id: str = "",
    hypothesis_id: str = "",
) -> None:
    """
    Convenience function for structured logging.

    Writes to .logs/app_debug.log only if DEBUG_LOG_TO_FILE=true.

    Args:
        location: Code location identifier (e.g., "module.py:function:entry")
        message: Human-readable log message
        data: Optional dictionary of structured data
        level: Log level ("debug", "info", "warning", "error")
        session_id: Optional session identifier
        run_id: Optional run identifier
        hypothesis_id: Optional hypothesis identifier
    """
    if session_id:
        _module_logger.set_session_id(session_id)
    if hypothesis_id:
        _module_logger.set_hypothesis_id(hypothesis_id)

    _module_logger.structured_log(location, message, data, level, run_id)
