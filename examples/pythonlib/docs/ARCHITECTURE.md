# mware Architecture

This document describes the internal architecture of the mware library.

## Core Design Philosophy

### Zero-Overhead Abstraction
The middleware pattern should add minimal runtime overhead. We achieve this through:
- Compile-time optimizations using decorators
- Lazy evaluation of middleware chains
- Careful memory management of context objects

### Type Safety First
Every API is designed with type safety as the primary concern:
- Full generic type support for context propagation
- Mypy strict mode compliance
- Runtime type validation in development mode

## Internal Components

### 1. Middleware Registry
```python
class MiddlewareRegistry:
    """Central registry for all middleware instances"""
    _instances: Dict[str, MiddlewareFunc]
    _metadata: Dict[str, MiddlewareMetadata]
```

### 2. Context Implementation
```python
class Context:
    """Immutable context object with copy-on-write semantics"""
    __slots__ = ('_data', '_parent', '_modified')
    
    def __setattr__(self, name, value):
        # Copy-on-write for performance
        if self._parent is not None:
            self._data = self._parent._data.copy()
            self._parent = None
        self._data[name] = value
```

### 3. Chain Execution Engine
```python
class ChainExecutor:
    """Optimized executor for middleware chains"""
    
    async def execute(self, chain: List[Middleware], context: Context):
        # Pre-compile chain for optimal performance
        compiled = self._compile_chain(chain)
        return await compiled(context)
```

## Performance Optimizations

### 1. Context Pooling
- Pre-allocated context objects to reduce GC pressure
- Thread-local pools for multi-threaded applications
- Automatic pool size adjustment based on load

### 2. Chain Compilation
- JIT compilation of middleware chains
- Inline simple middleware functions
- Eliminate redundant context copies

### 3. Async Optimization
- Zero-allocation async/await implementation
- Coroutine pooling for frequently used patterns
- Automatic sync-to-async adapter with minimal overhead

## Error Handling

### Error Context Enhancement
```python
class MiddlewareError(Exception):
    def __init__(self, message, context, middleware_stack):
        self.context = context
        self.stack = middleware_stack
        # Enhanced error messages with context
```

### Debug Mode
- Automatic stack trace enhancement
- Context snapshot at each middleware layer
- Performance profiling per middleware

## Extension Points

### 1. Custom Context Types
```python
class TypedContext(Context, Generic[T]):
    """Type-safe context with custom attributes"""
    pass
```

### 2. Middleware Composers
```python
class Composer:
    @staticmethod
    def parallel(*middlewares) -> Middleware:
        """Execute middlewares in parallel"""
    
    @staticmethod
    def conditional(predicate, middleware) -> Middleware:
        """Conditionally execute middleware"""
```

### 3. Adapters
- Framework-specific adapters (FastAPI, Flask, Django)
- Protocol adapters (HTTP, WebSocket, gRPC)
- Custom transport layers

## Memory Layout

### Context Object Layout
```
Context Instance (64 bytes):
├── _data (dict pointer): 8 bytes
├── _parent (Context pointer): 8 bytes
├── _modified (bool): 1 byte
├── _pool_ref (Pool pointer): 8 bytes
└── padding: 39 bytes
```

### Middleware Instance Layout
```
Middleware Instance (48 bytes):
├── func (callable): 8 bytes
├── name (str pointer): 8 bytes
├── metadata (dict pointer): 8 bytes
├── next (Middleware pointer): 8 bytes
├── flags (int): 8 bytes
└── reserved: 8 bytes
```

## Threading Model

### Global Interpreter Lock (GLL) Considerations
- Context pools are thread-local
- Middleware registry uses read-write locks
- Chain compilation is thread-safe

### Async Concurrency
- Full asyncio integration
- Trio compatibility layer
- Custom event loop support

## Future Considerations

### 1. Native Extensions
- Critical path implementation in Cython/C
- SIMD optimizations for context operations
- GPU acceleration for parallel middleware

### 2. Distributed Tracing
- OpenTelemetry native integration
- Distributed context propagation
- Cross-service middleware chains

### 3. WebAssembly Support
- WASM compilation for edge deployment
- Browser-compatible middleware chains
- Cross-platform binary distribution