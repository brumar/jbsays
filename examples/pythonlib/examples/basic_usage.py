#!/usr/bin/env python3
"""
Basic usage examples for the mware middleware library.

This file demonstrates the core concepts and patterns for using mware
to create composable, type-safe middleware decorators.
"""

import asyncio
import time
from typing import Any, Dict, Optional

from mware import middleware, Context


# Example 1: Simple timing middleware
@middleware
async def timing_middleware(ctx: Context, next) -> Any:
    """Track execution time of wrapped functions."""
    start = time.time()
    result = await next(ctx)
    ctx.execution_time = time.time() - start
    print(f"Function {ctx.func_name} took {ctx.execution_time:.3f} seconds")
    return result


# Example 2: Authentication middleware
@middleware
async def auth_middleware(ctx: Context, next) -> Any:
    """Ensure user is authenticated before executing function."""
    # In a real app, you'd check headers, tokens, etc.
    if not hasattr(ctx, 'user_id') or ctx.user_id is None:
        raise PermissionError("Authentication required")
    
    print(f"Authenticated user: {ctx.user_id}")
    return await next(ctx)


# Example 3: Logging middleware
@middleware
async def logging_middleware(ctx: Context, next) -> Any:
    """Log function calls and results."""
    print(f"Calling {ctx.func_name} with args={ctx.args}, kwargs={ctx.kwargs}")
    
    try:
        result = await next(ctx)
        print(f"{ctx.func_name} completed successfully")
        return result
    except Exception as e:
        print(f"{ctx.func_name} failed with error: {e}")
        raise


# Example 4: Caching middleware
cache_store: Dict[str, Any] = {}

@middleware
async def cache_middleware(ctx: Context, next) -> Any:
    """Simple in-memory cache for function results."""
    # Create cache key from function name and arguments
    cache_key = f"{ctx.func_name}:{ctx.args}:{ctx.kwargs}"
    
    # Check if result is already cached
    if cache_key in cache_store:
        print(f"Cache hit for {cache_key}")
        return cache_store[cache_key]
    
    # Execute function and cache result
    print(f"Cache miss for {cache_key}")
    result = await next(ctx)
    cache_store[cache_key] = result
    return result


# Example 5: Using middleware decorators

@timing_middleware
async def slow_function(n: int) -> int:
    """Simulate a slow operation."""
    await asyncio.sleep(n)
    return n * 2


@logging_middleware
@timing_middleware
async def calculate_fibonacci(n: int) -> int:
    """Calculate fibonacci number recursively."""
    if n <= 1:
        return n
    
    # In real code, you'd want to optimize this
    fib1 = await calculate_fibonacci(n - 1)
    fib2 = await calculate_fibonacci(n - 2)
    return fib1 + fib2


@logging_middleware
@auth_middleware
@cache_middleware
@timing_middleware
async def get_user_data(user_id: int) -> Dict[str, Any]:
    """Fetch user data with multiple middleware layers."""
    # Simulate database call
    await asyncio.sleep(0.1)
    return {
        "id": user_id,
        "name": f"User {user_id}",
        "email": f"user{user_id}@example.com"
    }


# Example 6: Middleware with configuration
def rate_limit(max_calls: int = 10, window_seconds: int = 60):
    """Factory for creating rate limiting middleware."""
    call_times: Dict[str, list] = {}
    
    @middleware
    async def rate_limit_middleware(ctx: Context, next) -> Any:
        current_time = time.time()
        key = f"{ctx.func_name}:{getattr(ctx, 'user_id', 'anonymous')}"
        
        # Initialize or clean old entries
        if key not in call_times:
            call_times[key] = []
        
        # Remove old calls outside the window
        call_times[key] = [t for t in call_times[key] 
                          if current_time - t < window_seconds]
        
        # Check rate limit
        if len(call_times[key]) >= max_calls:
            raise RuntimeError(f"Rate limit exceeded: {max_calls} calls per {window_seconds}s")
        
        # Record this call
        call_times[key].append(current_time)
        
        return await next(ctx)
    
    return rate_limit_middleware


@rate_limit(max_calls=3, window_seconds=10)
@timing_middleware
async def api_endpoint(data: str) -> Dict[str, str]:
    """Simulated API endpoint with rate limiting."""
    await asyncio.sleep(0.05)
    return {"status": "success", "data": data}


# Example 7: Error handling middleware
@middleware
async def error_handler_middleware(ctx: Context, next) -> Any:
    """Gracefully handle errors and provide fallback responses."""
    try:
        return await next(ctx)
    except ValueError as e:
        print(f"Handling ValueError: {e}")
        return {"error": "Invalid input", "message": str(e)}
    except PermissionError as e:
        print(f"Handling PermissionError: {e}")
        return {"error": "Access denied", "message": str(e)}
    except Exception as e:
        print(f"Handling unexpected error: {e}")
        return {"error": "Internal error", "message": "An unexpected error occurred"}


@error_handler_middleware
async def risky_operation(value: int) -> Dict[str, Any]:
    """Operation that might fail."""
    if value < 0:
        raise ValueError("Value must be non-negative")
    if value > 100:
        raise PermissionError("Value too large")
    
    return {"result": value * 2}


# Example 8: Context manipulation
@middleware
async def context_enrichment_middleware(ctx: Context, next) -> Any:
    """Add useful information to the context."""
    ctx.request_id = f"req_{int(time.time() * 1000)}"
    ctx.start_time = time.time()
    
    # Add mock user information
    ctx.user_id = 12345
    ctx.user_role = "admin"
    
    result = await next(ctx)
    
    # Add response metadata
    ctx.response_time = time.time() - ctx.start_time
    ctx.success = True
    
    return result


@context_enrichment_middleware
@auth_middleware
async def protected_operation() -> Dict[str, str]:
    """Operation that requires authentication and uses context."""
    return {
        "message": "Operation completed",
        "user": str(ctx.user_id),  # Access context within function
        "role": ctx.user_role
    }


async def main():
    """Run all examples."""
    print("=== mware Basic Usage Examples ===\n")
    
    # Example 1: Simple timing
    print("1. Timing middleware:")
    result = await slow_function(1)
    print(f"Result: {result}\n")
    
    # Example 2: Multiple middleware layers
    print("2. Multiple middleware (logging + timing):")
    fib_result = await calculate_fibonacci(5)
    print(f"Fibonacci(5) = {fib_result}\n")
    
    # Example 3: Authenticated and cached function
    print("3. Auth + Cache + Timing middleware:")
    # Set up context for authentication
    ctx.user_id = 42
    
    # First call - cache miss
    user_data1 = await get_user_data(1)
    print(f"First call result: {user_data1}")
    
    # Second call - cache hit
    user_data2 = await get_user_data(1)
    print(f"Second call result: {user_data2}\n")
    
    # Example 4: Rate limiting
    print("4. Rate limiting middleware:")
    for i in range(5):
        try:
            response = await api_endpoint(f"request_{i}")
            print(f"Request {i}: {response}")
        except RuntimeError as e:
            print(f"Request {i}: {e}")
    print()
    
    # Example 5: Error handling
    print("5. Error handling middleware:")
    
    # Valid operation
    result1 = await risky_operation(50)
    print(f"Valid operation: {result1}")
    
    # Invalid operation (negative value)
    result2 = await risky_operation(-10)
    print(f"Invalid operation: {result2}")
    
    # Invalid operation (too large)
    result3 = await risky_operation(150)
    print(f"Too large operation: {result3}\n")
    
    # Example 6: Context enrichment
    print("6. Context enrichment middleware:")
    protected_result = await protected_operation()
    print(f"Protected operation result: {protected_result}")
    print(f"Request completed in {ctx.response_time:.3f} seconds")


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())