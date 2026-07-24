import sys
sys.path.insert(0, '.')
import logging
logging.basicConfig(level=logging.INFO)
from modules.launcher.app_launcher import get_app_launcher

launcher = get_app_launcher()
print('Test 3: launcher.launch("visual studio")')
result = launcher.launch('visual studio')
print('Result:', result)