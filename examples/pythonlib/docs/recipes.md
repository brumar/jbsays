# mware - Common Recipes & Solutions

Quick solutions to common middleware challenges. Copy, paste, and customize for your needs.

## Authentication & Authorization

### JWT Token Validation

```python
import jwt
from mware import middleware

@middleware
async def jwt_auth_middleware(ctx, next):
    """Validate JWT tokens and extract user info."""
    auth_header = ctx.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        raise AuthError('Missing or invalid Authorization header')
    
    token = auth_header.split(' ', 1)[1]
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        ctx.user_id = payload['user_id']
        ctx.user_role = payload.get('role', 'user')
        ctx.token_data = payload
    except jwt.ExpiredSignatureError:
        raise AuthError('Token has expired')
    except jwt.InvalidTokenError:
        raise AuthError('Invalid token')
    
    return await next(ctx)

# Usage
@jwt_auth_middleware
async def protected_route(data):
    return {"user_id": ctx.user_id, "data": data}
```

### Role-Based Access Control

```python
def require_role(*allowed_roles):
    """Factory for role-based access control."""
    @middleware
    async def role_middleware(ctx, next):
        if not hasattr(ctx, 'user_role'):
            raise AuthError('No user role in context')
        
        if ctx.user_role not in allowed_roles:
            raise PermissionError(f'Requires role: {allowed_roles}')
        
        return await next(ctx)
    
    return role_middleware

# Usage
@require_role('admin', 'moderator')
async def admin_action(action):
    return {"status": "completed", "action": action}
```

### API Key Authentication

```python
@middleware
async def api_key_middleware(ctx, next):
    """Validate API key from header or query param."""
    api_key = ctx.headers.get('X-API-Key') or ctx.query_params.get('api_key')
    
    if not api_key:
        raise AuthError('API key required')
    
    # Validate API key (usually against database)
    client = await validate_api_key(api_key)
    if not client:
        raise AuthError('Invalid API key')
    
    ctx.client_id = client['id']
    ctx.rate_limit = client['rate_limit']
    ctx.permissions = client['permissions']
    
    return await next(ctx)
```

## Caching Strategies

### TTL-Based Cache

```python
from datetime import datetime, timedelta
from functools import lru_cache

def cache_with_ttl(ttl_seconds=300):
    """Cache results with time-to-live."""
    cache = {}
    
    @middleware
    async def ttl_cache_middleware(ctx, next):
        cache_key = f"{ctx.func_name}:{ctx.args}:{ctx.kwargs}"
        
        # Check cache
        if cache_key in cache:
            value, expiry = cache[cache_key]
            if datetime.now() < expiry:
                ctx.cache_hit = True
                return value
        
        # Cache miss
        ctx.cache_hit = False
        result = await next(ctx)
        
        # Store in cache
        expiry = datetime.now() + timedelta(seconds=ttl_seconds)
        cache[cache_key] = (result, expiry)
        
        return result
    
    return ttl_cache_middleware

# Usage
@cache_with_ttl(ttl_seconds=3600)  # 1 hour cache
async def fetch_user_profile(user_id):
    return await db.get_user(user_id)
```

### Redis Cache

```python
import redis
import json
import hashlib

redis_client = redis.Redis(decode_responses=True)

def redis_cache(expire_seconds=300, key_prefix="mware"):
    """Cache using Redis backend."""
    @middleware
    async def redis_cache_middleware(ctx, next):
        # Generate cache key
        key_data = f"{ctx.func_name}:{ctx.args}:{ctx.kwargs}"
        cache_key = f"{key_prefix}:{hashlib.md5(key_data.encode()).hexdigest()}"
        
        # Try to get from cache
        cached = await redis_client.get(cache_key)
        if cached:
            ctx.cache_hit = True
            return json.loads(cached)
        
        # Cache miss
        ctx.cache_hit = False
        result = await next(ctx)
        
        # Store in cache
        await redis_client.setex(
            cache_key, 
            expire_seconds, 
            json.dumps(result)
        )
        
        return result
    
    return redis_cache_middleware

# Usage
@redis_cache(expire_seconds=600, key_prefix="api")
async def expensive_calculation(params):
    return await compute_result(params)
```

### Cache Invalidation

```python
class CacheManager:
    """Manage cache with invalidation support."""
    def __init__(self):
        self.cache = {}
        self.dependencies = {}  # Track dependencies for invalidation
    
    def cache_middleware(self, depends_on=None):
        @middleware
        async def middleware(ctx, next):
            cache_key = self._make_key(ctx)
            
            # Check cache
            if cache_key in self.cache:
                return self.cache[cache_key]
            
            # Execute function
            result = await next(ctx)
            
            # Store in cache
            self.cache[cache_key] = result
            
            # Track dependencies
            if depends_on:
                for dep in depends_on:
                    if dep not in self.dependencies:
                        self.dependencies[dep] = set()
                    self.dependencies[dep].add(cache_key)
            
            return result
        
        return middleware
    
    def invalidate(self, dependency):
        """Invalidate all cache entries that depend on this key."""
        if dependency in self.dependencies:
            for cache_key in self.dependencies[dependency]:
                if cache_key in self.cache:
                    del self.cache[cache_key]
            del self.dependencies[dependency]
    
    def _make_key(self, ctx):
        return f"{ctx.func_name}:{id(ctx.args)}:{id(ctx.kwargs)}"

# Usage
cache_manager = CacheManager()

@cache_manager.cache_middleware(depends_on=['user_123'])
async def get_user_posts(user_id):
    return await db.fetch_posts(user_id)

# Invalidate when user data changes
async def update_user(user_id, data):
    await db.update_user(user_id, data)
    cache_manager.invalidate(f'user_{user_id}')
```

## Request/Response Transformation

### Input Validation

```python
from pydantic import BaseModel, ValidationError

def validate_input(model_class: BaseModel):
    """Validate input using Pydantic models."""
    @middleware
    async def validation_middleware(ctx, next):
        try:
            # Get input data from context
            input_data = ctx.request_data or {}
            
            # Validate using Pydantic
            validated = model_class(**input_data)
            
            # Replace with validated data
            ctx.validated_input = validated
            ctx.request_data = validated.dict()
            
        except ValidationError as e:
            return {
                "error": "validation_failed",
                "details": e.errors()
            }
        
        return await next(ctx)
    
    return validation_middleware

# Usage
class CreateUserRequest(BaseModel):
    username: str
    email: str
    age: int

@validate_input(CreateUserRequest)
async def create_user(user_data):
    return await db.create_user(ctx.validated_input)
```

### Response Formatting

```python
@middleware
async def response_formatter_middleware(ctx, next):
    """Standardize API responses."""
    try:
        result = await next(ctx)
        
        # Wrap successful responses
        return {
            "success": True,
            "data": result,
            "timestamp": datetime.now().isoformat(),
            "request_id": ctx.request_id
        }
    
    except Exception as e:
        # Format errors consistently
        return {
            "success": False,
            "error": {
                "type": type(e).__name__,
                "message": str(e),
                "code": getattr(e, 'code', 'UNKNOWN_ERROR')
            },
            "timestamp": datetime.now().isoformat(),
            "request_id": ctx.request_id
        }

# Usage
@response_formatter_middleware
async def api_endpoint(params):
    return {"result": "data"}
    # Returns: {"success": true, "data": {"result": "data"}, ...}
```

### Request Logging

```python
import logging
import time
import json

logger = logging.getLogger(__name__)

@middleware
async def request_logging_middleware(ctx, next):
    """Log all requests with timing and details."""
    start_time = time.time()
    
    # Log request
    logger.info(f"Request started: {ctx.func_name}", extra={
        "function": ctx.func_name,
        "args": ctx.args,
        "kwargs": ctx.kwargs,
        "user_id": getattr(ctx, 'user_id', None),
        "request_id": ctx.request_id
    })
    
    try:
        result = await next(ctx)
        duration = time.time() - start_time
        
        # Log success
        logger.info(f"Request completed: {ctx.func_name}", extra={
            "function": ctx.func_name,
            "duration": duration,
            "status": "success",
            "request_id": ctx.request_id
        })
        
        return result
    
    except Exception as e:
        duration = time.time() - start_time
        
        # Log failure
        logger.error(f"Request failed: {ctx.func_name}", extra={
            "function": ctx.func_name,
            "duration": duration,
            "status": "error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "request_id": ctx.request_id
        }, exc_info=True)
        
        raise
```

## Rate Limiting

### Token Bucket Algorithm

```python
import asyncio
from collections import defaultdict

class TokenBucket:
    """Token bucket rate limiter."""
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.buckets = defaultdict(lambda: {
            'tokens': capacity,
            'last_update': time.time()
        })
    
    async def consume(self, key: str, tokens: int = 1) -> bool:
        bucket = self.buckets[key]
        now = time.time()
        
        # Refill tokens
        elapsed = now - bucket['last_update']
        bucket['tokens'] = min(
            self.capacity,
            bucket['tokens'] + elapsed * self.refill_rate
        )
        bucket['last_update'] = now
        
        # Try to consume tokens
        if bucket['tokens'] >= tokens:
            bucket['tokens'] -= tokens
            return True
        
        return False
    
    def rate_limit_middleware(self, key_func=None):
        """Create rate limiting middleware."""
        @middleware
        async def middleware(ctx, next):
            # Determine rate limit key
            if key_func:
                key = key_func(ctx)
            else:
                key = getattr(ctx, 'user_id', ctx.client_ip)
            
            # Check rate limit
            if not await self.consume(key):
                raise RateLimitError("Rate limit exceeded")
            
            return await next(ctx)
        
        return middleware

# Usage
limiter = TokenBucket(capacity=100, refill_rate=10)  # 100 requests, 10/second refill

@limiter.rate_limit_middleware()
async def api_call(data):
    return {"processed": data}
```

### Sliding Window Rate Limiter

```python
import time
from collections import deque

class SlidingWindowLimiter:
    """Sliding window rate limiter."""
    def __init__(self, window_seconds: int, max_requests: int):
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self.requests = defaultdict(deque)
    
    def rate_limit_middleware(self):
        @middleware
        async def middleware(ctx, next):
            key = f"{ctx.user_id}:{ctx.func_name}"
            now = time.time()
            
            # Remove old requests outside window
            requests = self.requests[key]
            while requests and requests[0] < now - self.window_seconds:
                requests.popleft()
            
            # Check if limit exceeded
            if len(requests) >= self.max_requests:
                retry_after = self.window_seconds - (now - requests[0])
                raise RateLimitError(
                    f"Rate limit exceeded. Retry after {retry_after:.0f}s"
                )
            
            # Record this request
            requests.append(now)
            
            return await next(ctx)
        
        return middleware

# Usage
limiter = SlidingWindowLimiter(window_seconds=60, max_requests=100)

@limiter.rate_limit_middleware()
async def limited_endpoint(data):
    return process(data)
```

## Retries & Resilience

### Exponential Backoff Retry

```python
import random
import asyncio
from typing import Tuple, Type

def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2,
    jitter: bool = True,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """Retry with exponential backoff."""
    @middleware
    async def retry_middleware(ctx, next):
        last_exception = None
        
        for attempt in range(max_attempts):
            try:
                return await next(ctx)
            
            except retryable_exceptions as e:
                last_exception = e
                
                if attempt == max_attempts - 1:
                    break
                
                # Calculate delay
                delay = min(
                    base_delay * (exponential_base ** attempt),
                    max_delay
                )
                
                # Add jitter
                if jitter:
                    delay *= (0.5 + random.random())
                
                ctx.retry_attempt = attempt + 1
                ctx.retry_delay = delay
                
                await asyncio.sleep(delay)
        
        raise last_exception
    
    return retry_middleware

# Usage
@retry_with_backoff(
    max_attempts=5,
    base_delay=0.5,
    retryable_exceptions=(ConnectionError, TimeoutError)
)
async def flaky_api_call():
    return await external_api.request()
```

### Timeout with Fallback

```python
@middleware
async def timeout_with_fallback(timeout_seconds: float, fallback_value=None):
    """Timeout with optional fallback value."""
    async def timeout_middleware(ctx, next):
        try:
            return await asyncio.wait_for(
                next(ctx),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            if fallback_value is not None:
                return fallback_value
            
            raise TimeoutError(
                f"Operation timed out after {timeout_seconds}s"
            )
    
    return timeout_middleware

# Usage
@timeout_with_fallback(timeout_seconds=5.0, fallback_value={"status": "timeout"})
async def slow_operation():
    await asyncio.sleep(10)
    return {"result": "completed"}
```

## Monitoring & Metrics

### Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge

# Define metrics
request_count = Counter(
    'mware_requests_total',
    'Total number of requests',
    ['function', 'status']
)

request_duration = Histogram(
    'mware_request_duration_seconds',
    'Request duration in seconds',
    ['function']
)

active_requests = Gauge(
    'mware_active_requests',
    'Number of active requests',
    ['function']
)

@middleware
async def prometheus_metrics_middleware(ctx, next):
    """Collect Prometheus metrics."""
    start_time = time.time()
    
    # Track active requests
    active_requests.labels(function=ctx.func_name).inc()
    
    try:
        result = await next(ctx)
        
        # Record success
        request_count.labels(
            function=ctx.func_name,
            status='success'
        ).inc()
        
        return result
    
    except Exception as e:
        # Record failure
        request_count.labels(
            function=ctx.func_name,
            status='error'
        ).inc()
        
        raise
    
    finally:
        # Record duration and cleanup
        duration = time.time() - start_time
        request_duration.labels(function=ctx.func_name).observe(duration)
        active_requests.labels(function=ctx.func_name).dec()

# Usage
@prometheus_metrics_middleware
async def monitored_endpoint(data):
    return await process(data)
```

### Custom Business Metrics

```python
class MetricsCollector:
    """Collect custom business metrics."""
    def __init__(self):
        self.metrics = defaultdict(lambda: defaultdict(float))
    
    def track(self, metric_name: str, tags: dict = None):
        """Decorator to track specific metrics."""
        @middleware
        async def metrics_middleware(ctx, next):
            result = await next(ctx)
            
            # Allow function to set metrics
            if hasattr(ctx, 'metrics'):
                for name, value in ctx.metrics.items():
                    key = self._make_key(name, tags)
                    self.metrics[metric_name][key] += value
            
            return result
        
        return metrics_middleware
    
    def increment(self, metric_name: str, value: float = 1, tags: dict = None):
        """Increment a metric."""
        key = self._make_key(metric_name, tags)
        self.metrics[metric_name][key] += value
    
    def _make_key(self, name: str, tags: dict = None):
        if not tags:
            return name
        tag_str = ','.join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name},{tag_str}"

# Usage
metrics = MetricsCollector()

@metrics.track("revenue", tags={"currency": "USD"})
async def process_payment(amount, currency):
    # Track revenue metric
    ctx.metrics = {"revenue": amount}
    
    result = await payment_gateway.charge(amount, currency)
    return result
```

## Async Patterns

### Concurrent Execution Control

```python
import asyncio
from asyncio import Semaphore

def concurrency_limit(max_concurrent: int):
    """Limit concurrent executions of a function."""
    semaphore = Semaphore(max_concurrent)
    
    @middleware
    async def concurrency_middleware(ctx, next):
        async with semaphore:
            ctx.concurrent_executions = max_concurrent - semaphore._value
            return await next(ctx)
    
    return concurrency_middleware

# Usage
@concurrency_limit(max_concurrent=5)
async def api_call(url):
    return await fetch(url)

# Process many URLs with max 5 concurrent
urls = ["http://example.com/1", "http://example.com/2", ...]
results = await asyncio.gather(*[api_call(url) for url in urls])
```

### Async Queue Processing

```python
class AsyncQueueProcessor:
    """Process items through async queue with middleware."""
    def __init__(self, process_func, max_workers: int = 10):
        self.queue = asyncio.Queue()
        self.process_func = process_func
        self.max_workers = max_workers
        self.workers = []
    
    async def start(self):
        """Start queue workers."""
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(i))
            self.workers.append(worker)
    
    async def stop(self):
        """Stop all workers."""
        # Signal workers to stop
        for _ in range(self.max_workers):
            await self.queue.put(None)
        
        # Wait for workers to finish
        await asyncio.gather(*self.workers)
    
    async def _worker(self, worker_id: int):
        """Worker coroutine."""
        while True:
            item = await self.queue.get()
            
            if item is None:
                break
            
            try:
                ctx = Context()
                ctx.worker_id = worker_id
                ctx.item = item
                
                await self.process_func(ctx)
            
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
            
            finally:
                self.queue.task_done()
    
    async def put(self, item):
        """Add item to queue."""
        await self.queue.put(item)

# Usage
@timing_middleware
@error_handler_middleware
async def process_item(ctx):
    item = ctx.item
    # Process item
    return await handle_item(item)

processor = AsyncQueueProcessor(process_item, max_workers=5)
await processor.start()

# Add items to process
for item in items:
    await processor.put(item)

# Wait for completion
await processor.queue.join()
await processor.stop()
```

## Testing Helpers

### Test Fixtures

```python
import pytest
from mware import Context

@pytest.fixture
def mock_context():
    """Create mock context for testing."""
    ctx = Context()
    ctx.user_id = 123
    ctx.request_id = "test-123"
    ctx.headers = {"Authorization": "Bearer test-token"}
    return ctx

@pytest.fixture
def middleware_test_helper():
    """Helper for testing middleware."""
    class MiddlewareTestHelper:
        def __init__(self):
            self.calls = []
        
        async def test_function(self, ctx):
            self.calls.append(('function', ctx))
            return "test_result"
        
        async def mock_next(self, ctx):
            self.calls.append(('next', ctx))
            return await self.test_function(ctx)
    
    return MiddlewareTestHelper()

# Usage in tests
async def test_auth_middleware(mock_context, middleware_test_helper):
    result = await auth_middleware(
        mock_context,
        lambda ctx: middleware_test_helper.mock_next(ctx)
    )
    
    assert result == "test_result"
    assert len(middleware_test_helper.calls) == 2
    assert middleware_test_helper.calls[0][0] == 'next'
```

### Performance Testing

```python
import asyncio
import statistics
from typing import List

async def benchmark_middleware(
    middleware_func,
    test_func,
    iterations: int = 1000
) -> dict:
    """Benchmark middleware performance."""
    times_with_middleware: List[float] = []
    times_without_middleware: List[float] = []
    
    # Test with middleware
    wrapped_func = middleware_func(test_func)
    
    for _ in range(iterations):
        start = time.perf_counter()
        await wrapped_func()
        times_with_middleware.append(time.perf_counter() - start)
    
    # Test without middleware
    for _ in range(iterations):
        start = time.perf_counter()
        await test_func()
        times_without_middleware.append(time.perf_counter() - start)
    
    return {
        "with_middleware": {
            "mean": statistics.mean(times_with_middleware),
            "median": statistics.median(times_with_middleware),
            "stdev": statistics.stdev(times_with_middleware)
        },
        "without_middleware": {
            "mean": statistics.mean(times_without_middleware),
            "median": statistics.median(times_without_middleware),
            "stdev": statistics.stdev(times_without_middleware)
        },
        "overhead": {
            "mean": statistics.mean(times_with_middleware) - statistics.mean(times_without_middleware),
            "percentage": ((statistics.mean(times_with_middleware) / statistics.mean(times_without_middleware)) - 1) * 100
        }
    }

# Usage
async def test_function():
    await asyncio.sleep(0.001)
    return "result"

stats = await benchmark_middleware(
    timing_middleware,
    test_function,
    iterations=1000
)

print(f"Middleware overhead: {stats['overhead']['percentage']:.2f}%")
```

These recipes provide ready-to-use solutions for common middleware patterns. Combine and customize them to build robust, production-ready applications with mware.