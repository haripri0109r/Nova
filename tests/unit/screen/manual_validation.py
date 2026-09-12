"""
Manual validation script for ScreenContextBuilder.
Run this script manually to verify screen context building works on a real desktop.
"""
import sys
sys.path.insert(0, 'src')

from nova.screen.context import ScreenContextBuilder
from nova.screen.accessibility import get_accessibility


def main():
    print("=== Nova ScreenContextBuilder Manual Validation ===\n")
    
    # Check UI Automation availability
    acc = get_accessibility()
    if not acc.is_available():
        print("[FAIL] UI Automation not available")
        print("   Install uiautomation: pip install uiautomation")
        return 1
    
    print("[OK] UI Automation available")
    
    # Get foreground window info
    info = get_accessibility().get_foreground_window_info()
    if not info:
        print("[FAIL] No active window found")
        return 1
    
    print("\nActive Window Info:")
    print(f"   Process: {info.get('process_name', 'Unknown')}")
    print(f"   Title: {info.get('title', 'Unknown')}")
    print(f"   Class: {info.get('class_name', 'Unknown')}")
    print(f"   PID: {info.get('process_id', 'Unknown')}")
    if info.get('rect'):
        rect = info['rect']
        print(f"   Rect: ({rect[0]}, {rect[1]}, {rect[2]}, {rect[3]})")
    
    # Build screen context
    builder = ScreenContextBuilder()
    context = builder.build()
    
    print(f"\nScreenContext:")
    print(f"   Application: {context.application}")
    print(f"   Window Title: {context.window_title}")
    print(f"   Elements found: {len(context.elements)}")
    print(f"   Visible text items: {len(context.visible_text)}")
    
    if context.active_element:
        elem = context.active_element
        print(f"\nFocused Element:")
        print(f"   Role: {elem.role}")
        print(f"   Name: {elem.name}")
        print(f"   Text: {elem.text}")
        print(f"   Automation ID: {elem.automation_id}")
        print(f"   Class: {elem.class_name}")
        print(f"   BBox: {elem.bbox}")
        print(f"   Focused: {elem.focused}")
        print(f"   Clickable: {elem.clickable}")
    else:
        print("\nNo focused element detected")
    
    print(f"\nTop 10 Elements:")
    for i, elem in enumerate(context.elements[:10]):
        clickable = " [CLICKABLE]" if elem.clickable else ""
        focused = " [FOCUSED]" if elem.focused else ""
        text_preview = elem.text[:30] if elem.text else 'no text'
        print(f"   {i+1}. [{elem.role}] {elem.name} ({text_preview}){clickable}{focused}")
    
    if context.visible_text:
        print(f"\nVisible Text (first 10):")
        for i, text in enumerate(context.visible_text[:10]):
            print(f"   {i+1}. {text[:80]}")
    
    print("\n[OK] Manual validation complete")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())