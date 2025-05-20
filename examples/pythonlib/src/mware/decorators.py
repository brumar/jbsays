"""
Built-in middleware decorators for common use cases.
"""

import time
import asyncio
from typing import Any, Callable, Optional

from .core import middleware
from .context import Context
from .types import Next


@middleware
async def timing_middleware(ctx: Context, next: Next) -> Any:
    """
    Middleware that measures execution time of the wrapped handler.
    
    Adds the execution time to the context as 'timing' attribute.
    """
    start = time.perf_counter()
    try:
        result = await next(ctx)
        return result
    finally:
        elapsed = time.perf_counter() - start
        ctx.timing = elapsed


@middleware
async def error_middleware(ctx: Context, next: Next) -> Any:
    """
    Middleware that catches exceptions and adds error info to context.
    
    Adds 'error' and 'error_handled' attributes to the context.
    """
    try:
        return await next(ctx)
    except Exception as e:
        ctx.error = e
        ctx.error_handled = False
        raise


@middleware
async def retry_middleware(ctx: Context, next: Next) -> Any:
    """
    Middleware that retries the handler on failure.
    
    Uses 'max_retries' from context (default: 3) and 'retry_delay' (default: 0.1).
    """
    max_retries = ctx.get('max_retries', 3)
    retry_delay = ctx.get('retry_delay', 0.1)
    
    last_error = None
    for attempt in range(max_retries):
        try:
            return await next(ctx)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                continue
            raise
    
    # This should never be reached, but for type safety
    raise last_error  # type: ignore


@middleware
async def logging_middleware(ctx: Context, next: Next) -> Any:
    """
    Middleware that logs handler execution.
    
    Uses 'logger' from context if available, otherwise uses print.
    """
    logger = ctx.get('logger')
    handler_name = ctx.get('handler_name', 'unknown')
    
    if logger:
        logger.info(f"Starting handler: {handler_name}")
    else:
        print(f"Starting handler: {handler_name}")
    
    try:
        result = await next(ctx)
        if logger:
            logger.info(f"Handler {handler_name} completed successfully")
        else:
            print(f"Handler {handler_name} completed successfully")
        return result
    except Exception as e:
        if logger:
            logger.error(f"Handler {handler_name} failed: {str(e)}")
        else:
            print(f"Handler {handler_name} failed: {str(e)}")
        raise


def with_context(**kwargs: Any) -> Callable:
    """
    Decorator to inject context attributes before handler execution.
    
    Example:
        @with_context(user_id=123, request_id="abc")
        @some_middleware
        def handler(ctx):
            # ctx.user_id and ctx.request_id are available
            pass
    """
    def decorator(func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args: Any, **kw: Any) -> Any:
                if args and isinstance(args[0], Context):
                    ctx = args[0]
                    ctx.update(**kwargs)
                else:
                    # Create new context with the provided kwargs
                    ctx = Context(**kwargs)
                    args = (ctx,) + args
                return await func(*args, **kw)
            return async_wrapper
        else:
            def sync_wrapper(*args: Any, **kw: Any) -> Any:
                if args and isinstance(args[0], Context):
                    ctx = args[0]
                    ctx.update(**kwargs)
                else:
                    # Create new context with the provided kwargs
                    ctx = Context(**kwargs)
                    args = (ctx,) + args
                return func(*args, **kw)
            return sync_wrapper
    return decorator
