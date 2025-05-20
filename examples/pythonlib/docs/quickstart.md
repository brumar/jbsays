# mware - Quickstart Guide

Build composable, type-safe middleware decorators with an exceptional developer experience.

## Installation

```bash
pip install mware
```

## Your First Middleware

```python
from mware import middleware

@middleware
async def timing_middleware(ctx, next):
    """Track execution time of wrapped functions."""
    import time
    start = time.time()
    result = await next(ctx)
    ctx.timing = time.time() - start
    return result

# Apply middleware to any async function
@timing_middleware
async def fetch_user(user_id: int):
    # Simulate API call
    await asyncio.sleep(0.1)
    return {"id": user_id, "name": "Alice"}

# Usage
user = await fetch_user(123)
print(f"Execution time: {timing_middleware.ctx.timing}s")
```

## Composing Middleware

Stack multiple middleware decorators for powerful composition:

```python
@middleware
async def auth_middleware(ctx, next):
    """Ensure user is authenticated."""
    if not ctx.user_id:
        raise AuthError("Authentication required")
    return await next(ctx)

@middleware
async def cache_middleware(ctx, next):
    """Cache results for 60 seconds."""
    cache_key = f"{ctx.func_name}:{ctx.args}:{ctx.kwargs}"
    if cache_key in ctx.cache:
        return ctx.cache[cache_key]
    
    result = await next(ctx)
    ctx.cache[cache_key] = result
    return result

# Stack middleware - executed top to bottom
@timing_middleware
@auth_middleware
@cache_middleware
async def get_user_profile(user_id: int):
    # Your business logic here
    return await db.fetch_user(user_id)
```

## Error Handling

Built-in error middleware provides clean error handling:

```python
from mware import error_middleware

@error_middleware(
    on_error=lambda ctx, error: logger.error(f"Error in {ctx.func_name}: {error}"),
    fallback={"error": "Something went wrong"}
)
@timing_middleware
async def risky_operation():
    if random.random() > 0.5:
        raise ValueError("Random failure")
    return {"success": True}
```

## Context Object

The context object carries data through your middleware chain:

```python
@middleware
async def user_context_middleware(ctx, next):
    # Add user info to context
    ctx.user = await get_current_user()
    ctx.permissions = await get_user_permissions(ctx.user.id)
    return await next(ctx)

@user_context_middleware
async def delete_post(post_id: int):
    # Access context data in your function
    if "delete" not in ctx.permissions:
        raise PermissionError("Cannot delete post")
    return await db.delete_post(post_id)
```

## Type Safety

Full type hints ensure excellent IDE support:

```python
from mware import Middleware, Context
from typing import TypeVar, Callable

T = TypeVar('T')

@middleware
async def typed_middleware(ctx: Context, next: Callable[[], T]) -> T:
    # Your middleware gets full type inference
    result = await next()
    return result

# Applied function maintains its type signature
@typed_middleware
async def get_count() -> int:
    return 42

count: int = await get_count()  # Type checker knows this returns int
```

## Synchronous Functions

mware works seamlessly with both async and sync functions:

```python
@middleware
def sync_timing_middleware(ctx, next):
    import time
    start = time.time()
    result = next(ctx)
    ctx.timing = time.time() - start
    return result

@sync_timing_middleware
def calculate_fibonacci(n: int) -> int:
    if n <= 1:
        return n
    return calculate_fibonacci(n-1) + calculate_fibonacci(n-2)
```

## Advanced Patterns

### Conditional Middleware

```python
@middleware
async def conditional_cache(ctx, next):
    # Only cache GET requests
    if ctx.method != "GET":
        return await next(ctx)
    
    # Cache logic here...
    return await next(ctx)
```

### Middleware Factories

```python
def rate_limit(max_calls: int, window: int):
    @middleware
    async def rate_limit_middleware(ctx, next):
        key = f"{ctx.func_name}:{ctx.user_id}"
        if ctx.calls[key] > max_calls:
            raise RateLimitError(f"Max {max_calls} calls per {window}s")
        
        ctx.calls[key] += 1
        return await next(ctx)
    
    return rate_limit_middleware

# Usage
@rate_limit(max_calls=10, window=60)
async def api_endpoint():
    return {"status": "ok"}
```

### Global Middleware

Apply middleware to all functions in a module:

```python
from mware import apply_global_middleware

# Apply to all functions in current module
apply_global_middleware([
    timing_middleware,
    error_middleware,
    logging_middleware
])
```

## Best Practices

1. **Order Matters**: Middleware executes top-to-bottom. Place error handling first, authentication second.

2. **Keep It Simple**: Each middleware should have a single responsibility.

3. **Use Context Wisely**: Don't pollute context with unnecessary data.

4. **Type Everything**: Use type hints for better IDE support and fewer bugs.

5. **Test Middleware**: Write tests for your middleware separately from business logic.

## IDE Integration

mware provides excellent IDE support:

- Full autocompletion for context attributes
- Type inference for wrapped functions  
- Inline documentation
- Jump-to-definition support

## What's Next?

- Read the [API Reference](api.md) for detailed documentation
- Explore [Common Patterns](patterns.md) for real-world examples
- Check out [examples/](../examples/) for complete working code
- Join our [Discord community](https://discord.gg/mware) for support

---

*Building middleware should be a joy. We hope mware makes your code more composable, maintainable, and elegant.*