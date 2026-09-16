# System skills package
# Import submodules to trigger registration

from . import volume, brightness, shutdown, restart, sleep, lock, settings, wifi, bluetooth, personalization, display, audio, network, window, power  # noqa: F401

__all__ = [
    "volume",
    "brightness",
    "shutdown",
    "restart",
    "sleep",
    "lock",
    "settings",
    "wifi",
    "bluetooth",
    "personalization",
    "display",
    "audio",
    "network",
    "window",
    "power",
]