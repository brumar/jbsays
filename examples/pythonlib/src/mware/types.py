"""
Type definitions for the mware library.
"""

from typing import Any, Awaitable, Callable, TypeVar, Union

from .context import Context

# Type variables
T = TypeVar('T')
R = TypeVar('R')

# Type for the next function in middleware chain
Next = Callable[[Context], Union[Any, Awaitable[Any]]]

# Type for synchronous middleware function
Middleware = Callable[[Context, Next], Any]

# Type for asynchronous middleware function
AsyncMiddleware = Callable[[Context, Next], Awaitable[Any]]

# Type for middleware that can be either sync or async
AnyMiddleware = Union[Middleware, AsyncMiddleware]

# Type for handler functions
Handler = Callable[..., Any]
AsyncHandler = Callable[..., Awaitable[Any]]
AnyHandler = Union[Handler, AsyncHandler]

# Type for middleware decorator
MiddlewareDecorator = Callable[[AnyHandler], AnyHandler]
