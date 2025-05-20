"""
Tests for built-in middleware decorators.
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch

from mware.decorators import (
    timing_middleware,
    error_middleware, 
    retry_middleware,
    logging_middleware,
    with_context
)
from mware.context import Context


class TestTimingMiddleware:
    """Test the timing middleware decorator."""
    
    @pytest.mark.asyncio
    async def test_timing_records_execution_time(self):
        """Test that timing middleware records execution time."""
        @timing_middleware
        async def handler(ctx):
            await asyncio.sleep(0.01)  # Small delay
            return "result"
        
        ctx = Context()
        result = await handler(ctx)
        
        assert result == "result"
        assert hasattr(ctx, 'timing')
        assert ctx.timing > 0.01  # Should be at least 10ms
        
    @pytest.mark.asyncio
    async def test_timing_with_exception(self):
        """Test timing middleware still records time on exception."""
        @timing_middleware
        async def handler(ctx):
            await asyncio.sleep(0.01)
            raise ValueError("Test error")
        
        ctx = Context()
        with pytest.raises(ValueError):
            await handler(ctx)
        
        assert hasattr(ctx, 'timing')
        assert ctx.timing > 0.01


class TestErrorMiddleware:
    """Test the error handling middleware."""
    
    @pytest.mark.asyncio
    async def test_error_catches_exception(self):
        """Test that error middleware catches exceptions."""
        @error_middleware
        async def handler(ctx):
            raise ValueError("Test error")
        
        ctx = Context()
        with pytest.raises(ValueError) as exc_info:
            await handler(ctx)
        
        assert hasattr(ctx, 'error')
        assert ctx.error is exc_info.value
        assert hasattr(ctx, 'error_handled')
        assert ctx.error_handled is False
        
    @pytest.mark.asyncio 
    async def test_error_passes_through_result(self):
        """Test that error middleware passes through successful results."""
        @error_middleware
        async def handler(ctx):
            return "success"
        
        ctx = Context()
        result = await handler(ctx)
        
        assert result == "success"
        assert not hasattr(ctx, 'error')
        assert not hasattr(ctx, 'error_handled')


class TestRetryMiddleware:
    """Test the retry middleware."""
    
    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test that retry middleware retries on failure."""
        call_count = 0
        
        @retry_middleware
        async def handler(ctx):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary error")
            return "success"
        
        ctx = Context(max_retries=3, retry_delay=0.01)
        result = await handler(ctx)
        
        assert result == "success"
        assert call_count == 3
        
    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        """Test retry middleware when all attempts fail."""
        @retry_middleware
        async def handler(ctx):
            raise ValueError("Persistent error")
        
        ctx = Context(max_retries=2, retry_delay=0.01)
        with pytest.raises(ValueError, match="Persistent error"):
            await handler(ctx)
            
    @pytest.mark.asyncio
    async def test_retry_default_values(self):
        """Test retry with default values."""
        call_count = 0
        
        @retry_middleware
        async def handler(ctx):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("First failure")
            return "success"
        
        ctx = Context()  # No retry config
        result = await handler(ctx)
        
        assert result == "success"
        assert call_count == 2  # Used default max_retries


class TestLoggingMiddleware:
    """Test the logging middleware."""
    
    @pytest.mark.asyncio
    async def test_logging_with_logger(self):
        """Test logging middleware with a logger."""
        mock_logger = Mock()
        
        @logging_middleware
        async def handler(ctx):
            return "result"
        
        ctx = Context(logger=mock_logger, handler_name='test_handler')
        result = await handler(ctx)
        
        assert result == "result"
        mock_logger.info.assert_any_call("Starting handler: test_handler")
        mock_logger.info.assert_any_call("Handler test_handler completed successfully")
        
    @pytest.mark.asyncio
    async def test_logging_with_print(self):
        """Test logging middleware without logger (uses print)."""
        with patch('builtins.print') as mock_print:
            @logging_middleware
            async def handler(ctx):
                return "result"
            
            ctx = Context(handler_name='test_handler')
            result = await handler(ctx)
            
            assert result == "result"
            mock_print.assert_any_call("Starting handler: test_handler")
            mock_print.assert_any_call("Handler test_handler completed successfully")
            
    @pytest.mark.asyncio
    async def test_logging_on_error(self):
        """Test logging middleware on handler error."""
        mock_logger = Mock()
        
        @logging_middleware
        async def handler(ctx):
            raise ValueError("Test error")
        
        ctx = Context(logger=mock_logger, handler_name='failing_handler')
        
        with pytest.raises(ValueError):
            await handler(ctx)
        
        mock_logger.info.assert_called_with("Starting handler: failing_handler")
        mock_logger.error.assert_called_with("Handler failing_handler failed: Test error")


class TestWithContext:
    """Test the with_context decorator."""
    
    @pytest.mark.asyncio
    async def test_with_context_async_new_context(self):
        """Test with_context creates new context for async handlers."""
        @with_context(user_id=123, role='admin')
        async def handler(ctx):
            return {
                'user_id': ctx.user_id,
                'role': ctx.role
            }
        
        result = await handler()
        
        assert result['user_id'] == 123
        assert result['role'] == 'admin'
        
    def test_with_context_sync_new_context(self):
        """Test with_context creates new context for sync handlers."""
        @with_context(user_id=456, role='user')
        def handler(ctx):
            return {
                'user_id': ctx.user_id,
                'role': ctx.role
            }
        
        result = handler()
        
        assert result['user_id'] == 456
        assert result['role'] == 'user'
        
    @pytest.mark.asyncio
    async def test_with_context_existing_context(self):
        """Test with_context updates existing context."""
        @with_context(extra='value')
        async def handler(ctx):
            return {
                'original': ctx.original,
                'extra': ctx.extra
            }
        
        ctx = Context(original='data')
        result = await handler(ctx)
        
        assert result['original'] == 'data'
        assert result['extra'] == 'value'
        
    def test_with_context_sync_existing_context(self):
        """Test with_context updates existing sync context."""
        @with_context(extra='value')
        def handler(ctx):
            return {
                'original': ctx.original,
                'extra': ctx.extra
            }
        
        ctx = Context(original='data')
        result = handler(ctx)
        
        assert result['original'] == 'data'
        assert result['extra'] == 'value'