import sys
sys.path.insert(0, 'src')
import uiautomation as uia

# Build control type map
ct_map = {}
for name in dir(uia.ControlType):
    if not name.startswith('_'):
        val = getattr(uia.ControlType, name)
        if isinstance(val, int):
            ct_map[val] = name.replace('Control', '')

window = uia.WindowControl(searchDepth=1)
print('Window:', window.Name, window.ClassName)
print('Window.Exists():', window.Exists())

children = window.GetChildren()
print('Children count:', len(children))
for i, child in enumerate(children[:5]):
    role = ct_map.get(child.ControlType, 'ControlType_' + str(child.ControlType))
    name = getattr(child, 'Name', '') or ''
    text = getattr(child, 'Name', '') or ''
    automation_id = getattr(child, 'AutomationId', '') or ''
    class_name = getattr(child, 'ClassName', '') or ''
    
    bbox = None
    try:
        rect = child.BoundingRectangle
        if rect and rect.width() > 0 and rect.height() > 0:
            bbox = (rect.left, rect.top, rect.right, rect.bottom)
    except:
        pass
    
    enabled = True
    try:
        enabled = bool(getattr(child, 'IsEnabled', True))
    except:
        pass
    
    try:
        visible = bool(getattr(child, 'IsOffscreen', False)) == False
    except:
        pass
    
    clickable_types = {'Button', 'Hyperlink', 'MenuItem', 'ListItem', 'TabItem', 'TreeItem', 'CheckBox', 'RadioButton'}
    clickable = False
    if hasattr(child.ControlType, 'Name') and child.ControlType.Name in {'Button', 'Hyperlink', 'MenuItem', 'ListItem', 'TabItem', 'TreeItem', 'CheckBox', 'RadioButton'}:
        clickable = True
    
    try:
        focused = bool(getattr(child, 'HasKeyboardFocus', False))
    except:
        focused = False
    
    print(f'Child {i}: role={ct_map.get(child.ControlType, "ControlType_" + str(child.ControlType))} name={name} clickable={clickable} bbox={bbox}')