import sys
sys.path.insert(0, '.')
import logging
logging.basicConfig(level=logging.INFO)
from modules.launcher.app_launcher import get_app_launcher

launcher = get_app_launcher()

apps = ['chrome', 'vs code', 'whatsapp', 'calculator', 'paint', 'spotify', 'discord', 'telegram', 'steam', 'paint', 'notepad', 'word', 'excel', 'powerpoint', 'outlook', 'teams', 'terminal', 'cmd', 'powershell', 'notepad']

print('=== Full Test Suite ===')
for app in apps:
    print(f'--- Testing: {app} ---')
    result = launcher.launch(app)
    print(f'  Result: {result.status} (confidence: {result.confidence})')
    if result.matched_app:
        print(f'  Matched: {result.matched_app.get("name")} -> {result.path}')
    if result.candidates:
        print(f'  Candidates: {[c["name"] for c in result.candidates]}')
    print()