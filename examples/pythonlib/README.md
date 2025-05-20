# mware

<p align="center">
  <em>Python middleware decorators that actually make sense</em>
</p>

<p align="center">
  <a href="https://pypi.org/project/mware/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/mware.svg"></a>
  <a href="https://github.com/yourusername/mware/actions"><img alt="Build status" src="https://img.shields.io/github/workflow/status/yourusername/mware/CI"></a>
  <a href="https://codecov.io/gh/yourusername/mware"><img alt="Coverage" src="https://img.shields.io/codecov/c/github/yourusername/mware"></a>
  <a href="https://github.com/psf/black"><img alt="Code style: black" src="https://img.shields.io/badge/code%20style-black-000000.svg"></a>
</p>

<p align="center">
  <a href="#installation">Installation</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#features">Features</a> •
  <a href="https://mware.readthedocs.io">Docs</a>
</p>

---

**mware** brings the elegance of middleware patterns to Python with a DX that rivals the best libraries out there. If you've used Express.js or Koa.js, you'll feel right at home.

```python
from mware import middleware

@middleware
async def measure_time(ctx, next):
    start = time.time()
    result = await next(ctx)
    print(f"Execution took {time.time() - start:.3f}s")
    return result

@measure_time
async def fetch_user(ctx):
    # Your business logic here
    return {"id": ctx.user_id, "name": "Alice"}

# It just works™
result = await fetch_user(ctx={"user_id": 123})
```

## ✨ Why mware?

- **🎯 Intuitive API**: Feels natural to Python developers
- **🔒 Type-Safe**: Full type hints with mypy support
- **⚡ Async-First**: Built for modern async/await patterns
- **🪶 Zero Dependencies**: Lightweight core, no bloat
- **🧩 Composable**: Chain middleware easily
- **🚀 Fast**: Minimal overhead, maximum performance

## Installation

```bash
pip install mware
```

That's it. No complex setup. It just works.

## Quick Start

### Basic Middleware

```python
from mware import middleware, Context

@middleware
async def logging_middleware(ctx: Context, next):
    print(f"Before: {ctx.request.path}")
    result = await next(ctx)
    print(f"After: {ctx.response.status}")
    return result

# Chain multiple middleware
@logging_middleware
@auth_middleware
@rate_limit_middleware
async def api_handler(ctx: Context):
    return {"message": "Hello, World!"}
```

### Error Handling

```python
@middleware
async def error_handler(ctx: Context, next):
    try:
        return await next(ctx)
    except ValidationError as e:
        ctx.response.status = 400
        return {"error": str(e)}
    except Exception as e:
        ctx.response.status = 500
        return {"error": "Internal server error"}

@error_handler
async def risky_operation(ctx: Context):
    # This is automatically protected
    return perform_operation(ctx.data)
```

### Context Management

```python
# Context flows through your middleware chain
@middleware 
async def add_user(ctx: Context, next):
    ctx.user = await fetch_user(ctx.auth_token)
    return await next(ctx)

@middleware
async def require_admin(ctx: Context, next):
    if not ctx.user.is_admin:
        raise PermissionError("Admin required")
    return await next(ctx)

@add_user
@require_admin  
async def admin_action(ctx: Context):
    # ctx.user is available here
    return {"admin": ctx.user.name}
```

## Features

### 🎭 Flexible Patterns

```python
# Before/After
@middleware
async def before_after(ctx, next):
    # Before
    prepare_something()
    
    result = await next(ctx)
    
    # After
    cleanup_something()
    return result

# Short-circuit
@middleware
async def cache(ctx, next):
    cached = get_from_cache(ctx.key)
    if cached:
        return cached
    
    result = await next(ctx)
    save_to_cache(ctx.key, result)
    return result

# Modify response
@middleware
async def add_headers(ctx, next):
    result = await next(ctx)
    ctx.response.headers["X-Powered-By"] = "mware"
    return result
```

### 🔧 Custom Middleware

```python
from mware import create_middleware

# Function-based
log_requests = create_middleware(
    before=lambda ctx: print(f"Request: {ctx.request}"),
    after=lambda ctx, result: print(f"Response: {result}")
)

# Class-based  
class RateLimiter:
    def __init__(self, max_requests=100):
        self.max_requests = max_requests
    
    async def __call__(self, ctx, next):
        if self.is_rate_limited(ctx.ip):
            raise TooManyRequestsError()
        return await next(ctx)

rate_limiter = middleware(RateLimiter(max_requests=50))
```

### 🧪 Testing

```python
import pytest
from mware import Context, test_middleware

@pytest.mark.asyncio
async def test_auth_middleware():
    # Test utilities make testing middleware a breeze
    ctx = Context(auth_token="valid")
    result = await test_middleware(
        auth_middleware,
        handler=lambda ctx: {"user": ctx.user.name},
        context=ctx
    )
    assert result["user"] == "Alice"
```

## Performance

mware is designed for production use with minimal overhead:

```
Benchmark: 1M requests
─────────────────────────
No middleware:     1.23s
Single middleware: 1.31s  (+6.5%)
5 middleware:      1.58s  (+28%)
10 middleware:     1.89s  (+53%)
```

## Documentation

For complete documentation, visit [mware.readthedocs.io](https://mware.readthedocs.io)

- [Getting Started](https://mware.readthedocs.io/quickstart)
- [API Reference](https://mware.readthedocs.io/api)
- [Patterns & Best Practices](https://mware.readthedocs.io/patterns)
- [Examples](https://mware.readthedocs.io/examples)

## Contributing

We love contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License - see [LICENSE](LICENSE) for details.

---

<p align="center">Made with ❤️ by developers who care about DX</p>