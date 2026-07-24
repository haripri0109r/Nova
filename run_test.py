import subprocess, sys, time, os, signal
proc = subprocess.Popen([sys.executable, 'nova.py'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try:
    out, _ = proc.communicate(timeout=5)
except subprocess.TimeoutExpired:
    proc.terminate()
    out, _ = proc.communicate()
print(out.decode('utf-8', errors='replace'))