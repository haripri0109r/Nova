"""
Unit tests for ScreenElement dataclass.
"""
import pytest
import sys
sys.path.insert(0, 'src')

from nova.screen.elements import ScreenElement, ScreenContext


class TestScreenElement:
    """Tests for ScreenElement dataclass."""

    def test_construction_basic(self):
        """Test basic ScreenElement construction."""
        elem = ScreenElement(role="button", name="Test Button", bbox=(0, 0, 100, 50))
        assert elem.role == "button"
        assert elem.name == "Test Button"
        assert elem.bbox == (0, 0, 100, 50)
        assert elem.enabled is True
        assert elem.visible is True
        assert elem.clickable is False
        assert elem.focused is False

    def test_bbox_conversion_from_list(self):
        """Test bbox conversion from list to tuple."""
        elem = ScreenElement(role="button", bbox=[10, 20, 110, 70])
        assert elem.bbox == (10, 20, 110, 70)

    def test_center_property(self):
        """Test center property calculation."""
        elem = ScreenElement(bbox=(0, 0, 100, 100))
        assert elem.center == (50, 50)
        
        elem2 = ScreenElement(bbox=(10, 20, 110, 70))
        assert elem2.center == (60, 45)

    def test_area_property(self):
        """Test area property calculation."""
        elem = ScreenElement(bbox=(0, 0, 100, 50))
        assert elem.area == 5000
        
        elem2 = ScreenElement(bbox=(10, 10, 10, 10))  # zero area
        assert elem2.area == 0
        
        elem3 = ScreenElement()  # no bbox
        assert elem3.area == 0

    def test_to_dict(self):
        """Test to_dict serialization."""
        elem = ScreenElement(
            role="button",
            name="Test",
            text="Click me",
            automation_id="btn1",
            class_name="ButtonClass",
            bbox=(0, 0, 100, 50),
            enabled=True,
            visible=True,
            clickable=True,
            value="test",
            focused=True
        )
        d = elem.to_dict()
        assert d["role"] == "button"
        assert d["name"] == "Test"
        assert d["text"] == "Click me"
        assert d["automation_id"] == "btn1"
        assert d["class_name"] == "ButtonClass"
        assert d["bbox"] == (0, 0, 100, 50)
        assert d["enabled"] is True
        assert d["visible"] is True
        assert d["clickable"] is True
        assert d["value"] == "test"
        assert d["focused"] is True


class TestScreenContext:
    """Tests for ScreenContext dataclass."""

    def test_empty_context(self):
        """Test empty ScreenContext construction."""
        ctx = ScreenContext()
        assert ctx.application == ""
        assert ctx.window_title == ""
        assert ctx.active_element is None
        assert ctx.elements == []
        assert ctx.visible_text == []

    def test_context_with_data(self):
        """Test ScreenContext with data."""
        elem = ScreenElement(role="button", name="OK")
        ctx = ScreenContext(
            application="TestApp",
            window_title="Test Window",
            elements=[ScreenElement(role="text", name="Hello")],
            visible_text=["Hello", "World"]
        )
        assert ctx.application == "TestApp"
        assert ctx.window_title == "Test Window"
        assert len(ctx.elements) == 1
        assert ctx.visible_text == ["Hello", "World"]

    def test_context_to_dict(self):
        """Test ScreenContext to_dict serialization."""
        elem = ScreenElement(role="button", name="OK")
        ctx = ScreenContext(
            application="TestApp",
            window_title="Test",
            active_element=ScreenElement(role="button", name="OK"),
            elements=[ScreenElement(role="text", name="Hello")],
            visible_text=["Hello", "World"]
        )
        d = ctx.to_dict()
        assert d["application"] == "TestApp"
        assert d["window_title"] == "Test"
        assert d["active_element"]["role"] == "button"
        assert len(d["elements"]) == 1
        assert d["visible_text"] == ["Hello", "World"]

    def test_get_elements_by_role(self):
        """Test filtering elements by role."""
        ctx = ScreenContext(elements=[
            ScreenElement(role="button", name="OK"),
            ScreenElement(role="text", name="Hello"),
            ScreenElement(role="button", name="Cancel")
        ])
        buttons = ctx.get_elements_by_role("button")
        assert len(buttons) == 2
        assert all(e.role == "button" for e in buttons)

    def test_get_clickable_elements(self):
        """Test getting clickable elements."""
        ctx = ScreenContext(elements=[
            ScreenElement(role="button", name="OK", clickable=True),
            ScreenElement(role="text", name="Hello", clickable=False),
            ScreenElement(role="link", name="Link", clickable=True)
        ])
        clickable = ctx.get_clickable_elements()
        assert len(clickable) == 2
        assert all(e.clickable for e in clickable)

    def test_find_element_by_name(self):
        """Test finding element by name."""
        ctx = ScreenContext(elements=[
            ScreenElement(role="button", name="OK"),
            ScreenElement(role="button", name="Cancel")
        ])
        found = ctx.find_element_by_name("cancel")
        assert found is not None
        assert found.name == "Cancel"
        
        not_found = ctx.find_element_by_name("Submit")
        assert not_found is None

    def test_get_text_content(self):
        """Test getting all text as single string."""
        ctx = ScreenContext(visible_text=["Line 1", "Line 2", "Line 3"])
        content = ctx.get_text_content()
        assert content == "Line 1\nLine 2\nLine 3"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])