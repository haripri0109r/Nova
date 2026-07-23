import sounddevice as sd
import numpy as np
import time
from src.nova.audio_input import block_samples, _choose_input_device
from src.nova.config import SAMPLE_RATE, CHANNELS, BLOCK_MS

blocksize = block_samples()
idx = _choose_input_device(blocksize)
dev = sd.query_devices(idx)
print(f'Selected device index: {idx}')
print(f'Device name: {dev["name"]}')

peak = 0.0
with sd.InputStream(device=idx, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='float32', blocksize=blocksize) as stream:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        data, _ = stream.read(blocksize)
        if data.ndim > 1:
            data = np.mean(data.astype(np.float64), axis=1)
        else:
            data = data.astype(np.float64)
        rms = float(np.sqrt(np.mean(data**2))) if data.size else 0.0
        peak = max(peak, rms)
print(f'Peak RMS over 2 seconds: {peak:.6f}')