from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from llama_cpp import Llama

log = logging.getLogger("nova.intent.loader")

# ----------------------------------------------------------------------
# Configuration – can be overridden by env vars without code changes
# ----------------------------------------------------------------------
MODEL_PATH = Path(
    os.getenv(
        "NOVA_INTENT_MODEL",
        "models/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
    )
).expanduser().resolve()

# sensible defaults for a 0.5 B model on CPU
CTX_SIZE = int(os.getenv("NOVA_INTENT_CTX", "2048"))
N_THREADS = int(os.getenv("NOVA_INTENT_THREADS", str(os.cpu_count() or 4)))
N_GPU_LAYERS = int(os.getenv("NOVA_INTENT_GPU_LAYERS", "0"))   # 0 = CPU only


class ModelLoadError(RuntimeError):
    """Raised when the GGUF file cannot be loaded."""


class _ModelSingleton:
    """Lazy, process‑wide singleton – avoids re‑loading the 400 MB model."""
    _instance: Optional[Llama] = None

    @classmethod
    def get(cls) -> Llama:
        if cls._instance is None:
            if not MODEL_PATH.is_file():
                raise ModelLoadError(f"Intent model not found at {MODEL_PATH}")
            log.info("Loading intent model from %s (ctx=%d, threads=%d, gpu_layers=%d)",
                     MODEL_PATH, CTX_SIZE, N_THREADS, N_GPU_LAYERS)
            cls._instance = Llama(
                model_path=str(MODEL_PATH),
                n_ctx=CTX_SIZE,
                n_threads=N_THREADS,
                n_gpu_layers=N_GPU_LAYERS,
                verbose=False,                 # we handle logging ourselves
                seed=42,                       # deterministic for tests
            )
            log.info("Intent model loaded successfully")
        return cls._instance


def get_llm() -> Llama:
    """Public accessor – used by `engine.py`."""
    return _ModelSingleton.get()