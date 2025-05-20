"""
Tests for the core middleware implementation.
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock

from mware.core import middleware


class TestMiddlewareDecorator:
    """Test the @middleware decorator functionality."""
    
    def test_sync_middleware_with_sync_handler(self):
        """Test synchronous middleware wrapping a synchronous handler."""
        calls = []
        
        @middleware
        def timing_middleware(ctx, next):
            calls.append('before')
            result = next(ctx)
            calls.append('after')
            return result
        
        @timing_middleware
        def handler(ctx):
            calls.append('handler')
            return 'result'
        
        result = handler()
        
        assert result == 'result'
        assert calls == ['before', 'handler', 'after']
    
    @pytest.mark.asyncio
    async def test_async_middleware_with_async_handler(self):
        """Test asynchronous middleware wrapping an asynchronous handler."""
        calls = []
        
        @middleware
        async def timing_middleware(ctx, next):
            calls.append('before')
            result = await next(ctx)
            calls.append('after')
            return result
        
        @timing_middleware
        async def handler(ctx):
            calls.append('handler')
            return 'result'
        
        result = await handler()
        
        assert result == 'result'
        assert calls == ['before', 'handler', 'after']
    
    def test_sync_middleware_with_async_handler(self):
        """Test synchronous middleware wrapping an asynchronous handler."""
        calls = []
        
        @middleware
        def logging_middleware(ctx, next):
            calls.append('log_before')
            result = next(ctx)
            calls.append('log_after')
            return result
        
        @logging_middleware
        async def handler(ctx):
            calls.append('async_handler')
            return 'async_result'
        
        # Should automatically run in event loop
        result = handler()
        
        assert result == 'async_result'
        assert calls == ['log_before', 'async_handler', 'log_after']
    
    @pytest.mark.asyncio
    async def test_async_middleware_with_sync_handler(self):
        """Test asynchronous middleware wrapping a synchronous handler."""
        calls = []
        
        @middleware
        async def async_middleware(ctx, next):
            calls.append('async_before')
            result = await next(ctx)
            calls.append('async_after')
            return result
        
        @async_middleware
        def sync_handler(ctx):
            calls.append('sync_handler')
            return 'sync_result'
        
        # When called from async context, should work seamlessly
        result = await asyncio.create_task(sync_handler())
        
        assert result == 'sync_result'
        assert 'async_before' in calls
        assert 'sync_handler' in calls
        assert 'async_after' in calls
    
    def test_middleware_chaining(self):
        """Test multiple middleware decorators chained together."""
        calls = []
        
        @middleware
        def first_middleware(ctx, next):
            calls.append('first_before')
            result = next(ctx)
            calls.append('first_after')
            return result
        
        @middleware
        def second_middleware(ctx, next):
            calls.append('second_before')
            result = next(ctx)
            calls.append('second_after')
            return result
        
        @first_middleware
        @second_middleware
        def handler(ctx):
            calls.append('handler')
            return 'result'
        
        result = handler()
        
        assert result == 'result'
        assert calls == [
            'first_before',
            'second_before',
            'handler',
            'second_after',
            'first_after'
        ]
    
    def test_middleware_with_arguments(self):
        """Test middleware handling handler arguments."""
        @middleware
        def pass_through_middleware(ctx, next):
            return next(ctx)
        
        @pass_through_middleware
        def handler(ctx, arg1, arg2, kwarg1=None):
            return f'{arg1}-{arg2}-{kwarg1}'
        
        result = handler('a', 'b', kwarg1='c')
        assert result == 'a-b-c'
    
    def test_middleware_error_propagation(self):
        """Test that errors propagate through middleware chain."""
        @middleware
        def error_middleware(ctx, next):
            try:
                return next(ctx)
            except ValueError:
                raise
            except Exception:
                return 'caught'
        
        @error_middleware
        def handler(ctx):
            raise ValueError('test error')
        
        with pytest.raises(ValueError, match='test error'):
            handler()
    
    def test_middleware_modifying_result(self):
        """Test middleware modifying the result of the handler."""
        @middleware
        def transform_middleware(ctx, next):
            result = next(ctx)
            return result.upper()
        
        @transform_middleware
        def handler(ctx):
            return 'hello'
        
        result = handler()
        assert result == 'HELLO'