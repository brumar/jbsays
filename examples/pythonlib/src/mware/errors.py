"""
Advanced error handling with rich, developer-friendly error messages.

This module provides sophisticated error classes and utilities that enhance
the debugging experience for middleware users.
"""

import sys
import traceback
from typing import Any, Callable, Dict, List, Optional, Type, Union


class MiddlewareError(Exception):
    """Base exception for all middleware-related errors with enhanced debugging info."""
    
    def __init__(self, message: str, **metadata: Any) -> None:
        super().__init__(message)
        self.message = message
        self.metadata = metadata
        self._suggestions: List[str] = []
        self._related_errors: List[Exception] = []
        self._debug_info: Dict[str, Any] = {}
        
    def add_suggestion(self, suggestion: str) -> "MiddlewareError":
        """Add a helpful suggestion for fixing this error."""
        self._suggestions.append(suggestion)
        return self
        
    def add_related_error(self, error: Exception) -> "MiddlewareError":
        """Add a related error that might have caused this one."""
        self._related_errors.append(error)
        return self
        
    def add_debug_info(self, key: str, value: Any) -> "MiddlewareError":
        """Add debugging information."""
        self._debug_info[key] = value
        return self
        
    def __str__(self) -> str:
        """Generate a rich, formatted error message."""
        parts = [f"MiddlewareError: {self.message}"]
        
        if self.metadata:
            parts.append("\nError Context:")
            for key, value in self.metadata.items():
                parts.append(f"  {key}: {value}")
        
        if self._debug_info:
            parts.append("\nDebug Information:")
            for key, value in self._debug_info.items():
                parts.append(f"  {key}: {value}")
        
        if self._suggestions:
            parts.append("\nDid you mean?")
            for suggestion in self._suggestions:
                parts.append(f"  → {suggestion}")
        
        if self._related_errors:
            parts.append("\nRelated Errors:")
            for error in self._related_errors:
                parts.append(f"  - {type(error).__name__}: {error}")
        
        return "\n".join(parts)


class ConfigurationError(MiddlewareError):
    """Raised when middleware is incorrectly configured."""
    
    def __init__(self, message: str, field: Optional[str] = None, **metadata: Any) -> None:
        super().__init__(message, field=field, **metadata)
        if field:
            self.add_debug_info("configuration_field", field)


class ChainError(MiddlewareError):
    """Raised when there's an error in the middleware chain execution."""
    
    def __init__(self, message: str, position: Optional[int] = None, **metadata: Any) -> None:
        super().__init__(message, position=position, **metadata)
        if position is not None:
            self.add_debug_info("chain_position", position)


class ContextError(MiddlewareError):
    """Raised when there's an error with the context object."""
    
    def __init__(self, message: str, key: Optional[str] = None, **metadata: Any) -> None:
        super().__init__(message, key=key, **metadata)
        if key:
            self.add_debug_info("context_key", key)


class ValidationError(MiddlewareError):
    """Raised when input validation fails."""
    
    def __init__(self, message: str, field: Optional[str] = None, 
                 value: Any = None, **metadata: Any) -> None:
        super().__init__(message, field=field, value=value, **metadata)
        if field:
            self.add_debug_info("validation_field", field)
        if value is not None:
            self.add_debug_info("invalid_value", value)


def format_middleware_trace(error: Exception) -> str:
    """
    Format a traceback with middleware-specific highlighting and filtering.
    
    This provides cleaner stack traces that highlight relevant middleware code
    and filter out framework internals.
    """
    tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
    
    formatted_lines = []
    in_middleware = False
    
    for line in tb_lines:
        # Highlight lines from the mware package
        if "mware/" in line:
            if not in_middleware:
                formatted_lines.append("  ━━━ Middleware Stack ━━━\n")
                in_middleware = True
            formatted_lines.append(f"  → {line}")
        else:
            if in_middleware:
                formatted_lines.append("  ━━━━━━━━━━━━━━━━━━━━━━━\n")
                in_middleware = False
            # Filter out asyncio internals unless in debug mode
            if "asyncio" not in line or getattr(sys, "mware_debug", False):
                formatted_lines.append(line)
    
    return "".join(formatted_lines)


def create_error_handler(
    fallback: Optional[Callable[[Exception], Any]] = None,
    log_errors: bool = True,
    include_trace: bool = True,
) -> Callable:
    """
    Create a middleware error handler with customizable behavior.
    
    This is useful for creating application-wide error handling middleware.
    """
    async def error_handler_middleware(ctx: "Context", next: Callable) -> Any:
        try:
            return await next(ctx)
        except MiddlewareError as e:
            if log_errors:
                print(str(e), file=sys.stderr)
            if include_trace:
                print(format_middleware_trace(e), file=sys.stderr)
            if fallback:
                return fallback(e)
            raise
        except Exception as e:
            # Wrap non-middleware errors
            wrapped = MiddlewareError(
                f"Unexpected error in middleware chain: {type(e).__name__}"
            )
            wrapped.add_related_error(e)
            wrapped.add_debug_info("original_type", type(e).__name__)
            wrapped.add_debug_info("original_message", str(e))
            
            if log_errors:
                print(str(wrapped), file=sys.stderr)
            if include_trace:
                print(format_middleware_trace(e), file=sys.stderr)
            if fallback:
                return fallback(wrapped)
            raise wrapped from e
    
    return error_handler_middleware


class ErrorReporter:
    """
    Advanced error reporting with telemetry and debugging capabilities.
    """
    
    def __init__(self, app_name: str = "mware_app"):
        self.app_name = app_name
        self.error_count = 0
        self.error_history: List[Dict[str, Any]] = []
        
    def report(self, error: Exception) -> None:
        """Report an error with full context."""
        self.error_count += 1
        
        error_data = {
            "count": self.error_count,
            "type": type(error).__name__,
            "message": error.args[0] if error.args else "",
            "traceback": traceback.format_exc(),
            "metadata": getattr(error, "metadata", {}),
        }
        
        if isinstance(error, MiddlewareError):
            error_data.update({
                "suggestions": error._suggestions,
                "debug_info": error._debug_info,
                "related_errors": [str(e) for e in error._related_errors],
            })
        
        self.error_history.append(error_data)
        
        # In production, this would send to error tracking service
        if getattr(sys, "mware_debug", False):
            print(f"\n{'='*50}")
            print(f"Error Report #{self.error_count} - {self.app_name}")
            print(f"{'='*50}")
            for key, value in error_data.items():
                if key != "traceback":
                    print(f"{key}: {value}")
            print(f"{'='*50}\n")
    
    def get_report_summary(self) -> Dict[str, Any]:
        """Get a summary of all reported errors."""
        error_types = {}
        for error in self.error_history:
            error_type = error["type"]
            error_types[error_type] = error_types.get(error_type, 0) + 1
            
        return {
            "total_errors": self.error_count,
            "error_types": error_types,
            "last_error": self.error_history[-1] if self.error_history else None,
        }


# Global error reporter instance
error_reporter = ErrorReporter()