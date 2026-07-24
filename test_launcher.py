import sys
sys.path.insert(0, '.')
import logging
logging.basicConfig(level=logging.INFO)
from modules.launcher.app_launcher import get_app_launcher

launcher = get_app_launcher()
print('Test 1: launcher.launch("open chrome")')
result = launcher.launch('open chrome')
print('Result:', result)
print()
print('Test 2: launcher.launch("vs code")')
result = launcher.launch('vs code')
print('Result:', result)