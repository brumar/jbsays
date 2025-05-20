# mware - Advanced Patterns & Best Practices

This guide covers advanced patterns and best practices for building sophisticated middleware systems with mware.

## Table of Contents
1. [Middleware Composition Patterns](#middleware-composition-patterns)
2. [Context Management](#context-management)
3. [Error Handling Strategies](#error-handling-strategies)
4. [Performance Patterns](#performance-patterns)
5. [Testing Middleware](#testing-middleware)
6. [Real-world Examples](#real-world-examples)

## Middleware Composition Patterns

### The Onion Model

Middleware wraps functions like layers of an onion. Understanding execution order is crucial:

```python
@middleware_a  # Outer layer - executes first
@middleware_b  # Middle layer
@middleware_c  # Inner layer - executes last before the function
async def my_function():
    pass

# Execution order:
# 1. middleware_a (before)
# 2. middleware_b (before)
# 3. middleware_c (before)
# 4. my_function
# 5. middleware_c (after)
# 6. middleware_b (after)
# 7. middleware_a (after)
```

### Conditional Middleware Application

Apply middleware based on runtime conditions:

```python
def conditional_middleware(condition: Callable[[Context], bool]):
    """Apply middleware only when condition is met."""
    @middleware
    async def wrapper(ctx: Context, next):
        if condition(ctx):
            # Apply the actual middleware logic
            return await actual_middleware(ctx, next)
        # Skip middleware
        return await next(ctx)
    
    return wrapper

# Usage
@conditional_middleware(lambda ctx: ctx.user_role == "admin")
async def admin_only_operation():
    return {"sensitive": "data"}
```

### Middleware Composition Functions

Combine multiple middleware into reusable groups:

```python
def compose_middleware(*middlewares):
    """Compose multiple middleware into a single decorator."""
    def decorator(func):
        for mw in reversed(middlewares):
            func = mw(func)
        return func
    return decorator

# Define middleware groups
auth_stack = compose_middleware(
    timing_middleware,
    logging_middleware,
    auth_middleware,
    permission_middleware
)

cache_stack = compose_middleware(
    timing_middleware,
    cache_middleware,
    compression_middleware
)

# Apply composed middleware
@auth_stack
async def protected_endpoint():
    pass

@cache_stack
async def cached_endpoint():
    pass
```

## Context Management

### Context Isolation

Prevent context pollution between requests:

```python
from contextvars import ContextVar

request_context: ContextVar[Context] = ContextVar('request_context')

@middleware
async def isolated_context_middleware(ctx: Context, next):
    """Isolate context for each request."""
    # Create a fresh context copy
    isolated_ctx = Context()
    isolated_ctx.update(ctx.__dict__.copy())
    
    # Set the context for this request
    token = request_context.set(isolated_ctx)
    
    try:
        result = await next(isolated_ctx)
        return result
    finally:
        # Clean up context
        request_context.reset(token)
```

### Context Type Safety

Use TypedDict for type-safe context access:

```python
from typing import TypedDict, Optional
from mware import Context as BaseContext

class AppContext(TypedDict):
    user_id: int
    user_role: str
    request_id: str
    auth_token: Optional[str]
    permissions: List[str]

class TypedContext(BaseContext):
    """Typed context for better IDE support."""
    def __init__(self):
        super().__init__()
        self._data: AppContext = {}
    
    @property
    def user_id(self) -> int:
        return self._data.get('user_id')
    
    @user_id.setter
    def user_id(self, value: int):
        self._data['user_id'] = value
    
    # ... more typed properties
```

### Context Factories

Create specialized contexts for different use cases:

```python
def create_web_context(request) -> Context:
    """Create context from web request."""
    ctx = Context()
    ctx.method = request.method
    ctx.path = request.path
    ctx.headers = dict(request.headers)
    ctx.user_id = request.user_id
    return ctx

def create_cli_context(args) -> Context:
    """Create context from CLI arguments."""
    ctx = Context()
    ctx.command = args.command
    ctx.verbose = args.verbose
    ctx.user_id = os.getuid()
    return ctx
```

## Error Handling Strategies

### Layered Error Handling

Handle different error types at appropriate layers:

```python
@middleware
async def business_error_middleware(ctx: Context, next):
    """Handle business logic errors."""
    try:
        return await next(ctx)
    except ValidationError as e:
        return {"error": "validation_failed", "details": e.errors()}
    except BusinessRuleError as e:
        return {"error": "business_rule_violated", "message": str(e)}

@middleware
async def system_error_middleware(ctx: Context, next):
    """Handle system-level errors."""
    try:
        return await next(ctx)
    except DatabaseError as e:
        logger.error(f"Database error: {e}")
        return {"error": "service_unavailable", "message": "Database unavailable"}
    except TimeoutError as e:
        return {"error": "timeout", "message": "Request timed out"}

@middleware
async def critical_error_middleware(ctx: Context, next):
    """Last resort error handler."""
    try:
        return await next(ctx)
    except Exception as e:
        # Log critical error
        logger.critical(f"Unhandled error: {e}", exc_info=True)
        
        # Send to error tracking service
        if error_tracker:
            error_tracker.capture_exception(e, context=ctx)
        
        return {"error": "internal_server_error", "message": "An unexpected error occurred"}
```

### Circuit Breaker Pattern

Prevent cascading failures:

```python
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
    
    @middleware
    async def circuit_breaker_middleware(self, ctx: Context, next):
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
            else:
                raise CircuitOpenError("Circuit breaker is open")
        
        try:
            result = await next(ctx)
            if self.state == "half-open":
                self.state = "closed"
                self.failure_count = 0
            return result
        
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
            
            raise

# Usage
db_circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30)

@db_circuit_breaker.circuit_breaker_middleware
async def database_operation():
    return await db.query("SELECT * FROM users")
```

## Performance Patterns

### Batch Processing

Combine multiple requests into batches:

```python
from collections import defaultdict
import asyncio

class BatchProcessor:
    def __init__(self, batch_size: int = 10, batch_timeout: float = 0.1):
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.pending_requests = defaultdict(list)
        self.batch_lock = asyncio.Lock()
    
    @middleware
    async def batch_middleware(self, ctx: Context, next):
        batch_key = f"{ctx.func_name}:{ctx.args[0]}"  # Group by function and first arg
        
        async with self.batch_lock:
            future = asyncio.Future()
            self.pending_requests[batch_key].append((ctx, future))
            
            if len(self.pending_requests[batch_key]) >= self.batch_size:
                await self._process_batch(batch_key)
            else:
                asyncio.create_task(self._process_batch_after_timeout(batch_key))
        
        return await future
    
    async def _process_batch_after_timeout(self, batch_key: str):
        await asyncio.sleep(self.batch_timeout)
        await self._process_batch(batch_key)
    
    async def _process_batch(self, batch_key: str):
        if batch_key not in self.pending_requests:
            return
        
        requests = self.pending_requests.pop(batch_key)
        
        # Process all requests in the batch
        results = await batch_query([req[0] for req in requests])
        
        # Resolve all futures
        for (ctx, future), result in zip(requests, results):
            future.set_result(result)
```

### Lazy Loading

Load expensive resources only when needed:

```python
class LazyResource:
    def __init__(self, loader_func):
        self.loader_func = loader_func
        self._resource = None
        self._loading = False
        self._load_lock = asyncio.Lock()
    
    async def get(self):
        if self._resource is None:
            async with self._load_lock:
                if self._resource is None:  # Double-check pattern
                    self._resource = await self.loader_func()
        return self._resource

@middleware
async def lazy_loading_middleware(ctx: Context, next):
    """Lazy load expensive resources."""
    # Lazy load database connection
    ctx.db = LazyResource(lambda: create_db_connection())
    
    # Lazy load ML model
    ctx.ml_model = LazyResource(lambda: load_ml_model())
    
    return await next(ctx)

# Usage
@lazy_loading_middleware
async def predict(data):
    model = await ctx.ml_model.get()
    return model.predict(data)
```

### Resource Pooling

Manage shared resources efficiently:

```python
class ResourcePool:
    def __init__(self, create_func, max_size: int = 10):
        self.create_func = create_func
        self.max_size = max_size
        self.available = asyncio.Queue(maxsize=max_size)
        self.in_use = set()
    
    async def acquire(self):
        try:
            resource = self.available.get_nowait()
        except asyncio.QueueEmpty:
            if len(self.in_use) < self.max_size:
                resource = await self.create_func()
            else:
                resource = await self.available.get()
        
        self.in_use.add(resource)
        return resource
    
    async def release(self, resource):
        self.in_use.remove(resource)
        await self.available.put(resource)

# Connection pool middleware
connection_pool = ResourcePool(create_db_connection, max_size=20)

@middleware
async def connection_pool_middleware(ctx: Context, next):
    conn = await connection_pool.acquire()
    ctx.db_connection = conn
    
    try:
        result = await next(ctx)
        return result
    finally:
        await connection_pool.release(conn)
```

## Testing Middleware

### Mock Middleware for Testing

```python
import pytest
from unittest.mock import Mock, AsyncMock

@pytest.fixture
def mock_middleware():
    """Create a mock middleware for testing."""
    mock = AsyncMock()
    
    @middleware
    async def test_middleware(ctx: Context, next):
        mock.before(ctx)
        result = await next(ctx)
        mock.after(ctx, result)
        return result
    
    test_middleware.mock = mock
    return test_middleware

async def test_middleware_execution_order(mock_middleware):
    @mock_middleware
    async def test_function():
        return "result"
    
    result = await test_function()
    
    # Verify middleware was called in correct order
    assert mock_middleware.mock.before.called
    assert mock_middleware.mock.after.called
    assert mock_middleware.mock.before.call_args[0][0].func_name == "test_function"
    assert mock_middleware.mock.after.call_args[0][1] == "result"
```

### Context Testing

```python
class TestContext(Context):
    """Test context with predefined values."""
    def __init__(self, **kwargs):
        super().__init__()
        self.update(kwargs)

async def test_auth_middleware():
    # Test with authenticated user
    auth_ctx = TestContext(user_id=123, role="admin")
    
    @auth_middleware
    async def protected_function(ctx):
        return "success"
    
    result = await protected_function.with_context(auth_ctx)
    assert result == "success"
    
    # Test without authentication
    no_auth_ctx = TestContext()
    
    with pytest.raises(PermissionError):
        await protected_function.with_context(no_auth_ctx)
```

## Real-world Examples

### Web API Middleware Stack

```python
# Complete middleware stack for a production API
api_middleware_stack = compose_middleware(
    # Observability
    request_id_middleware,
    logging_middleware,
    metrics_middleware,
    tracing_middleware,
    
    # Security
    cors_middleware,
    rate_limit_middleware,
    auth_middleware,
    permission_middleware,
    
    # Performance
    compression_middleware,
    cache_middleware,
    batch_middleware,
    
    # Error handling
    error_handler_middleware,
    circuit_breaker_middleware,
    
    # Business logic
    validation_middleware,
    sanitization_middleware,
    transaction_middleware
)

@api_middleware_stack
async def api_endpoint(request):
    # Your business logic here
    pass
```

### Background Job Processing

```python
# Middleware for background job processing
job_middleware_stack = compose_middleware(
    # Monitoring
    job_tracking_middleware,
    metrics_middleware,
    
    # Reliability
    retry_middleware(max_attempts=3, backoff=exponential_backoff),
    timeout_middleware(seconds=300),
    
    # Resource management
    memory_limit_middleware(max_memory_mb=1024),
    cpu_limit_middleware(max_cpu_percent=80),
    
    # Error handling
    dead_letter_queue_middleware,
    alert_middleware(on_failure=send_alert_to_ops)
)

@job_middleware_stack
async def process_large_file(file_path: str):
    # Process file in chunks
    pass
```

### GraphQL Resolver Middleware

```python
# Middleware for GraphQL resolvers
graphql_middleware_stack = compose_middleware(
    # Performance
    dataloader_middleware,  # Batch & cache DB queries
    query_depth_limit_middleware(max_depth=7),
    query_complexity_middleware(max_complexity=1000),
    
    # Security
    field_auth_middleware,
    data_masking_middleware,
    
    # Monitoring
    field_timing_middleware,
    resolver_metrics_middleware
)

@graphql_middleware_stack
async def user_resolver(parent, args, context, info):
    return await fetch_user(args["id"])
```

## Best Practices Summary

1. **Layer your middleware**: Organize middleware from general to specific
2. **Keep middleware focused**: Each middleware should have a single responsibility
3. **Use context wisely**: Don't pollute context; use typed contexts when possible
4. **Handle errors appropriately**: Different error types at different layers
5. **Test middleware independently**: Mock dependencies and test edge cases
6. **Monitor performance**: Add metrics and logging to understand behavior
7. **Document middleware**: Clear documentation for each middleware's purpose
8. **Version your middleware**: Maintain backward compatibility when possible

Remember: Great middleware is invisible when it works and helpful when it doesn't.