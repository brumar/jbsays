"""
Tests for the error handling and error classes.
"""

import sys
import pytest
from typing import Callable
from mware.errors import (
    MiddlewareError,
    ConfigurationError,
    ChainError,
    ContextError,
    ValidationError,
    format_middleware_trace,
    create_error_handler,
    ErrorReporter
)
from mware.context import Context


class TestMiddlewareError:
    """Test the base MiddlewareError class."""
    
    def test_basic_error(self):
        """Test creating a basic middleware error."""
        error = MiddlewareError("Something went wrong")
        assert str(error).startswith("MiddlewareError: Something went wrong")
        assert error.message == "Something went wrong"
    
    def test_error_with_metadata(self):
        """Test error with metadata."""
        error = MiddlewareError("Error occurred", user_id=123, endpoint="/api/test")
        error_str = str(error)
        
        assert "Error Context:" in error_str
        assert "user_id: 123" in error_str
        assert "endpoint: /api/test" in error_str
    
    def test_error_with_suggestions(self):
        """Test adding suggestions to error."""
        error = MiddlewareError("Invalid configuration")
        error.add_suggestion("Try using 'timeout' instead of 'time_out'")
        error.add_suggestion("Check the documentation for valid options")
        
        error_str = str(error)
        assert "Did you mean?" in error_str
        assert "→ Try using 'timeout' instead of 'time_out'" in error_str
        assert "→ Check the documentation for valid options" in error_str
    
    def test_error_with_debug_info(self):
        """Test adding debug information."""
        error = MiddlewareError("Processing failed")
        error.add_debug_info("request_id", "abc123")
        error.add_debug_info("timestamp", 1234567890)
        
        error_str = str(error)
        assert "Debug Information:" in error_str
        assert "request_id: abc123" in error_str
        assert "timestamp: 1234567890" in error_str
    
    def test_error_with_related_errors(self):
        """Test adding related errors."""
        original_error = ValueError("Invalid value")
        error = MiddlewareError("Operation failed")
        error.add_related_error(original_error)
        
        error_str = str(error)
        assert "Related Errors:" in error_str
        assert "ValueError: Invalid value" in error_str
    
    def test_method_chaining(self):
        """Test that methods return self for chaining."""
        error = (MiddlewareError("Error")
                .add_suggestion("Try again")
                .add_debug_info("key", "value")
                .add_related_error(Exception("Related")))
        
        assert len(error._suggestions) == 1
        assert error._debug_info["key"] == "value"
        assert len(error._related_errors) == 1


class TestSpecializedErrors:
    """Test specialized error classes."""
    
    def test_configuration_error(self):
        """Test ConfigurationError."""
        error = ConfigurationError("Invalid config", field="timeout")
        error_str = str(error)
        
        assert "field: timeout" in error_str
        assert error._debug_info["configuration_field"] == "timeout"
    
    def test_chain_error(self):
        """Test ChainError."""
        error = ChainError("Chain broken", position=3)
        error_str = str(error)
        
        assert "position: 3" in error_str
        assert error._debug_info["chain_position"] == 3
    
    def test_context_error(self):
        """Test ContextError."""
        error = ContextError("Key not found", key="user_id")
        error_str = str(error)
        
        assert "key: user_id" in error_str
        assert error._debug_info["context_key"] == "user_id"
    
    def test_validation_error(self):
        """Test ValidationError."""
        error = ValidationError("Invalid input", field="email", value="not-an-email")
        error_str = str(error)
        
        assert "field: email" in error_str
        assert "value: not-an-email" in error_str
        assert error._debug_info["validation_field"] == "email"
        assert error._debug_info["invalid_value"] == "not-an-email"


class TestErrorHandling:
    """Test error handling utilities."""
    
    def test_format_middleware_trace(self):
        """Test formatting middleware traces."""
        try:
            raise MiddlewareError("Test error")
        except MiddlewareError as e:
            trace = format_middleware_trace(e)
            assert "MiddlewareError: Test error" in trace
    
    @pytest.mark.asyncio
    async def test_error_handler_middleware(self):
        """Test the error handler middleware factory."""
        fallback_called = False
        
        def fallback_handler(error):
            nonlocal fallback_called
            fallback_called = True
            return "fallback"
        
        error_handler = create_error_handler(
            fallback=fallback_handler,
            log_errors=False,
            include_trace=False
        )
        
        # Test successful execution
        async def success_next(ctx):
            return "success"
        
        ctx = Context()
        result = await error_handler(ctx, success_next)
        assert result == "success"
        assert not fallback_called
        
        # Test middleware error handling
        async def middleware_error_next(ctx):
            raise MiddlewareError("Middleware failed")
        
        result = await error_handler(ctx, middleware_error_next)
        assert result == "fallback"
        assert fallback_called
        
        # Test regular error handling
        fallback_called = False
        
        async def regular_error_next(ctx):
            raise ValueError("Regular error")
        
        result = await error_handler(ctx, regular_error_next)
        assert result == "fallback"
        assert fallback_called
    
    @pytest.mark.asyncio
    async def test_error_handler_reraise(self):
        """Test error handler that re-raises errors."""
        error_handler = create_error_handler(
            fallback=None,
            log_errors=False,
            include_trace=False
        )
        
        async def error_next(ctx):
            raise MiddlewareError("Test error")
        
        ctx = Context()
        with pytest.raises(MiddlewareError):
            await error_handler(ctx, error_next)


class TestErrorReporter:
    """Test the ErrorReporter class."""
    
    def test_basic_reporting(self):
        """Test basic error reporting."""
        reporter = ErrorReporter("test_app")
        
        error = MiddlewareError("Test error")
        reporter.report(error)
        
        assert reporter.error_count == 1
        assert len(reporter.error_history) == 1
        
        history_entry = reporter.error_history[0]
        assert history_entry["type"] == "MiddlewareError"
        assert history_entry["message"] == "Test error"
        assert history_entry["count"] == 1
    
    def test_reporting_with_metadata(self):
        """Test reporting errors with metadata."""
        reporter = ErrorReporter("test_app")
        
        error = MiddlewareError("Error with metadata", user_id=123)
        error.add_suggestion("Try again")
        error.add_debug_info("request_id", "abc")
        
        reporter.report(error)
        
        history_entry = reporter.error_history[0]
        assert history_entry["metadata"]["user_id"] == 123
        assert "Try again" in history_entry["suggestions"]
        assert history_entry["debug_info"]["request_id"] == "abc"
    
    def test_report_summary(self):
        """Test getting error report summary."""
        reporter = ErrorReporter("test_app")
        
        # Report different types of errors
        reporter.report(MiddlewareError("Error 1"))
        reporter.report(ValidationError("Error 2"))
        reporter.report(MiddlewareError("Error 3"))
        
        summary = reporter.get_report_summary()
        
        assert summary["total_errors"] == 3
        assert summary["error_types"]["MiddlewareError"] == 2
        assert summary["error_types"]["ValidationError"] == 1
        assert summary["last_error"]["message"] == "Error 3"
    
    def test_debug_mode_output(self, capsys):
        """Test debug mode output."""
        # Enable debug mode
        original_debug = getattr(sys, "mware_debug", None)
        sys.mware_debug = True
        
        try:
            reporter = ErrorReporter("test_app")
            reporter.report(MiddlewareError("Debug test"))
            
            captured = capsys.readouterr()
            assert "Error Report #1 - test_app" in captured.out
            assert "Debug test" in captured.out
        finally:
            # Restore original debug state
            if original_debug is None:
                delattr(sys, "mware_debug")
            else:
                sys.mware_debug = original_debug