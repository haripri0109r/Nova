import sys
sys.path.insert(0, '.')
import logging
logging.basicConfig(level=logging.DEBUG)
from modules.launcher.app_launcher import AppLauncher

launcher = AppLauncher()

original_launch = launcher._launch
def debug_launch(app):
    print(f'_launch called with app: {app["name"]} -> {app.get("path")}')
    return launcher._launch(app)

launcher._launch = debug_launch
result = launcher.launch('word')
print('Result:', result)