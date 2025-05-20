"""
Core middleware implementation with async-first design.
"""

import asyncio
import functools
from typing import Any, Callable, TypeVar, Union

from .context import Context
from .types import AsyncMiddleware, Middleware, Next

T = TypeVar("T")


def middleware(func: Union[Middleware, AsyncMiddleware]) -> Callable:
    """
    Decorator to create middleware functions that can be chained together.
    
    Supports both sync and async functions, with automatic detection.
    """
    is_async_middleware = asyncio.iscoroutinefunction(func)
    
    def decorator(handler: Callable) -> Callable:
        is_async_handler = asyncio.iscoroutinefunction(handler)
        
        @functools.wraps(handler)
        def wrapper(*args, **kwargs) -> Any:
            # Extract context
            if args and isinstance(args[0], Context):
                ctx = args[0]
                new_args = args[1:]
            else:
                ctx = Context()
                new_args = args
            
            # Case 1: Sync middleware with sync handler
            if not is_async_middleware and not is_async_handler:
                def next_fn(context: Context) -> Any:
                    return handler(context, *new_args, **kwargs)
                
                return func(ctx, next_fn)
            
            # Case 2: Sync middleware with async handler 
            # This needs to run the async handler in an event loop
            elif not is_async_middleware and is_async_handler:
                def next_fn(context: Context) -> Any:
                    # Run the async handler synchronously
                    return asyncio.run(handler(context, *new_args, **kwargs))
                
                return func(ctx, next_fn)
            
            # Cases with async middleware need async handling
            else:
                return asyncio.run(async_wrapper(*args, **kwargs))
        
        @functools.wraps(handler)
        async def async_wrapper(*args, **kwargs) -> Any:
            # Extract context
            if args and isinstance(args[0], Context):
                ctx = args[0]
                new_args = args[1:]
            else:
                ctx = Context()
                new_args = args
            
            # Case 3: Async middleware with async handler
            if is_async_middleware and is_async_handler:
                async def next_fn(context: Context) -> Any:
                    return await handler(context, *new_args, **kwargs)
                
                return await func(ctx, next_fn)
            
            # Case 4: Async middleware with sync handler
            elif is_async_middleware and not is_async_handler:
                async def next_fn(context: Context) -> Any:
                    # Run sync handler directly - no need for executor for simple sync functions
                    return handler(context, *new_args, **kwargs)
                
                return await func(ctx, next_fn)
            
            # This shouldn't happen, but handle it
            else:
                raise RuntimeError("Unexpected middleware/handler combination")
        
        # Choose wrapper based on what we need  
        # The key insight: if handler is async, ALWAYS need an async-capable wrapper
        # even with sync middleware
        if is_async_handler:
            # For async handlers, we need special handling
            if is_async_middleware:
                return async_wrapper
            else:
                # Sync middleware + async handler = needs special wrapper
                return wrapper
        else:
            # For sync handlers, return based on middleware type
            if is_async_middleware:
                return async_wrapper
            else:
                return wrapper
    
    return decorator