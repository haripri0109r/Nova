import sys
sys.path.insert(0, '.')
import logging
logging.basicConfig(level=logging.INFO)
from modules.launcher.app_launcher import get_app_launcher

launcher = get_app_launcher()
apps = ['spotify', 'discord', 'telegram', 'steam', 'excel', 'powerpoint', 'outlook', 'word']

for app in ['spotify', 'discord', 'telegram', 'steam', 'excel', 'powerpoint', 'outlook', 'word']:
    print(f'--- Testing: {app} ---')
    result = launcher.launch(app)
    print(f'Result: {result.status} (confidence: {result.confidence})')
    if result.matched_app:
        print(f'  Matched: {result.matched_app["name"]} -> {result.path}')
    if result.candidates:
        print(f'  Candidates: {[c["name"] for c in result.candidates]}')
    print()