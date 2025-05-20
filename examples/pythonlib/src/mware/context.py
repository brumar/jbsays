"""
Context object that flows through the middleware chain.
"""

from typing import Any, Dict, Optional


class Context:
    """
    Context object that carries data through the middleware chain.
    
    Provides a flexible way to pass data between middleware functions
    while maintaining type safety and clean interfaces.
    """
    
    def __init__(self, **kwargs: Any) -> None:
        """Initialize context with optional keyword arguments."""
        self._data: Dict[str, Any] = {}
        self._metadata: Dict[str, Any] = {}
        
        # Set initial data from kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def __getattr__(self, name: str) -> Any:
        """Get attribute from context data."""
        if name.startswith('_'):
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
        
        if name in self._data:
            return self._data[name]
        
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
    
    def __setattr__(self, name: str, value: Any) -> None:
        """Set attribute in context data."""
        if name.startswith('_'):
            # Internal attributes go directly to the instance
            super().__setattr__(name, value)
        else:
            # Public attributes go to the data dictionary
            if '_data' not in self.__dict__:
                super().__setattr__('_data', {})
            self._data[name] = value
    
    def __contains__(self, name: str) -> bool:
        """Check if attribute exists in context."""
        return name in self._data
    
    def get(self, name: str, default: Any = None) -> Any:
        """Get attribute with optional default value."""
        return self._data.get(name, default)
    
    def set(self, name: str, value: Any) -> None:
        """Set attribute value."""
        self._data[name] = value
    
    def update(self, **kwargs: Any) -> None:
        """Update multiple attributes at once."""
        self._data.update(kwargs)
    
    def clear(self) -> None:
        """Clear all context data."""
        self._data.clear()
    
    def keys(self) -> list:
        """Get all attribute names."""
        return list(self._data.keys())
    
    def values(self) -> list:
        """Get all attribute values."""
        return list(self._data.values())
    
    def items(self) -> list:
        """Get all attribute name-value pairs."""
        return list(self._data.items())
    
    def copy(self) -> 'Context':
        """Create a shallow copy of the context."""
        new_context = Context()
        new_context._data = self._data.copy()
        new_context._metadata = self._metadata.copy()
        return new_context
    
    def __repr__(self) -> str:
        """String representation of the context."""
        return f"Context({self._data})"
    
    def __str__(self) -> str:
        """Human-readable string representation."""
        items = ', '.join(f'{k}={v!r}' for k, v in self._data.items())
        return f"Context({items})"
