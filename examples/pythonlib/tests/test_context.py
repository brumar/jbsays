"""
Tests for the Context object implementation.
"""

import pytest
from mware.context import Context


class TestContext:
    """Test the Context object functionality."""
    
    def test_init_empty(self):
        """Test creating an empty context."""
        ctx = Context()
        assert len(ctx.keys()) == 0
        assert str(ctx) == "Context()"
        assert repr(ctx) == "Context({})"
    
    def test_init_with_kwargs(self):
        """Test creating context with initial values."""
        ctx = Context(user_id=123, is_admin=True, name="test")
        
        assert ctx.user_id == 123
        assert ctx.is_admin is True
        assert ctx.name == "test"
        assert len(ctx.keys()) == 3
    
    def test_attribute_access(self):
        """Test getting and setting attributes."""
        ctx = Context()
        
        # Test setting attributes
        ctx.request_id = "abc123"
        ctx.user = {"id": 1, "name": "Alice"}
        
        # Test getting attributes
        assert ctx.request_id == "abc123"
        assert ctx.user == {"id": 1, "name": "Alice"}
    
    def test_attribute_error(self):
        """Test accessing non-existent attributes."""
        ctx = Context()
        
        with pytest.raises(AttributeError):
            _ = ctx.non_existent
        
        with pytest.raises(AttributeError):
            _ = ctx._private_attr
    
    def test_contains(self):
        """Test the 'in' operator."""
        ctx = Context(foo="bar")
        
        assert "foo" in ctx
        assert "bar" not in ctx
        
        ctx.bar = "baz"
        assert "bar" in ctx
    
    def test_get_method(self):
        """Test get method with defaults."""
        ctx = Context(foo="bar")
        
        assert ctx.get("foo") == "bar"
        assert ctx.get("missing") is None
        assert ctx.get("missing", "default") == "default"
    
    def test_set_method(self):
        """Test set method."""
        ctx = Context()
        
        ctx.set("key", "value")
        assert ctx.key == "value"
        assert ctx.get("key") == "value"
    
    def test_update_method(self):
        """Test update method."""
        ctx = Context(a=1)
        
        ctx.update(b=2, c=3)
        assert ctx.a == 1
        assert ctx.b == 2
        assert ctx.c == 3
        
        ctx.update(a=10, d=4)
        assert ctx.a == 10
        assert ctx.d == 4
    
    def test_clear_method(self):
        """Test clear method."""
        ctx = Context(a=1, b=2, c=3)
        assert len(ctx.keys()) == 3
        
        ctx.clear()
        assert len(ctx.keys()) == 0
        assert "a" not in ctx
    
    def test_keys_values_items(self):
        """Test keys, values, and items methods."""
        ctx = Context(a=1, b=2, c=3)
        
        keys = ctx.keys()
        assert sorted(keys) == ["a", "b", "c"]
        
        values = ctx.values()
        assert sorted(values) == [1, 2, 3]
        
        items = ctx.items()
        assert sorted(items) == [("a", 1), ("b", 2), ("c", 3)]
    
    def test_copy(self):
        """Test copying context."""
        ctx1 = Context(a=1, b=[1, 2, 3])
        ctx2 = ctx1.copy()
        
        # Test that it's a different object
        assert ctx1 is not ctx2
        
        # Test that data is copied
        assert ctx2.a == 1
        assert ctx2.b == [1, 2, 3]
        
        # Test shallow copy behavior
        ctx2.a = 2
        assert ctx1.a == 1  # Original unchanged
        
        ctx2.b.append(4)
        assert ctx1.b == [1, 2, 3, 4]  # Original changed (shallow copy)
    
    def test_string_representations(self):
        """Test string and repr methods."""
        ctx = Context(user_id=123, is_admin=True)
        
        # Check that both representations include the data
        str_repr = str(ctx)
        repr_repr = repr(ctx)
        
        assert "user_id=123" in str_repr or "is_admin=True" in str_repr
        assert "123" in repr_repr and "True" in repr_repr
    
    def test_metadata_isolation(self):
        """Test that metadata is isolated from regular data."""
        ctx = Context()
        
        # Regular attributes shouldn't affect metadata
        ctx.user_id = 123
        assert "_metadata" not in ctx
        assert "user_id" not in ctx._metadata
        
        # Metadata should be preserved during copy
        ctx._metadata["request_time"] = 1234567890
        ctx2 = ctx.copy()
        
        assert ctx2._metadata["request_time"] == 1234567890
        assert ctx2.user_id == 123
    
    def test_complex_data_types(self):
        """Test storing complex data types in context."""
        ctx = Context()
        
        # Test various types
        ctx.list_data = [1, 2, 3]
        ctx.dict_data = {"nested": {"key": "value"}}
        ctx.tuple_data = (1, 2, 3)
        ctx.set_data = {1, 2, 3}
        ctx.none_data = None
        ctx.bool_data = False
        
        assert ctx.list_data == [1, 2, 3]
        assert ctx.dict_data == {"nested": {"key": "value"}}
        assert ctx.tuple_data == (1, 2, 3)
        assert ctx.set_data == {1, 2, 3}
        assert ctx.none_data is None
        assert ctx.bool_data is False
    
    def test_context_chaining(self):
        """Test using context in a chain-like pattern."""
        ctx = Context()
        
        # Test method chaining pattern
        ctx.set("a", 1)
        ctx.set("b", 2)
        ctx.update(c=3, d=4)
        
        assert ctx.a == 1
        assert ctx.b == 2
        assert ctx.c == 3
        assert ctx.d == 4