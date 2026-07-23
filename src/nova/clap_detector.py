#!/usr/bin/env python3
"""
Clap detection state machine: consumes RMS values and emits double-clap events.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Generator

from .config import (
    SPIKE_RATIO,
    COOLDOWN_S,
    MIN_DOUBLE_GAP_S,
    MAX_DOUBLE_GAP_S,
    RETRIGGER_RATIO,
    NOISE_FLOOR_ALPHA,
    MIN_RMS,
    QUIET_GATE_MULT,
)


@dataclass
class ClapDetectorState:
    noise_floor: float = 1e-4
    last_logged_double: float = 0.0
    first_clap_time: float | None = None
    spike_armed: bool = True


class ClapDetector:
    """
    Streaming double-clap detector.

    Feed RMS values via `update(rms, now)`.
    Returns True when a double-clap is detected.
    Attributes after detection: last_gap, noise_floor, threshold
    """

    def __init__(
        self,
        *,
        spike_ratio: float = SPIKE_RATIO,
        cooldown_s: float = COOLDOWN_S,
        min_double_gap_s: float = MIN_DOUBLE_GAP_S,
        max_double_gap_s: float = MAX_DOUBLE_GAP_S,
        retrigger_ratio: float = RETRIGGER_RATIO,
        noise_floor_alpha: float = NOISE_FLOOR_ALPHA,
        min_rms: float = MIN_RMS,
        quiet_gate_mult: float = QUIET_GATE_MULT,
    ) -> None:
        self.state = ClapDetectorState()
        self.spike_ratio = spike_ratio
        self.cooldown_s = cooldown_s
        self.min_double_gap_s = min_double_gap_s
        self.max_double_gap_s = max_double_gap_s
        self.retrigger_ratio = retrigger_ratio
        self.noise_floor_alpha = noise_floor_alpha
        self.min_rms = min_rms
        self.quiet_gate_mult = quiet_gate_mult

        # Public attributes updated on each call
        self.last_gap: float | None = None
        self.threshold: float = 0.0

    def update(self, level: float, now: float | None = None) -> bool:
        """
        Process a single RMS level reading.

        Returns:
            True if a double-clap was detected, else False.
        """
        if now is None:
            now = time.monotonic()

        # Update noise floor during quiet periods
        quiet_gate = self.state.noise_floor * self.quiet_gate_mult
        if level < quiet_gate:
            self.state.noise_floor = self.noise_floor_alpha * self.state.noise_floor + (
                1.0 - self.noise_floor_alpha
            ) * level
            self.state.noise_floor = max(self.state.noise_floor, 1e-7)

        self.threshold = max(self.state.noise_floor * self.spike_ratio, self.min_rms)
        retrigger_level = self.threshold * self.retrigger_ratio

        # Re-arm spike detection when level drops below retrigger threshold
        if level < retrigger_level:
            self.state.spike_armed = True

        # Detect spike
        if (
            self.state.spike_armed
            and level >= self.threshold
            and (now - self.state.last_logged_double) >= self.cooldown_s
        ):
            self.state.spike_armed = False
            if self.state.first_clap_time is None:
                self.state.first_clap_time = now
            else:
                gap = now - self.state.first_clap_time
                if gap < self.min_double_gap_s:
                    # Too fast; ignore and keep first_clap_time as-is
                    pass
                elif gap <= self.max_double_gap_s:
                    # Valid double clap
                    self.state.first_clap_time = None
                    self.state.last_logged_double = now
                    self.last_gap = gap
                    return True
                else:
                    # Too slow; treat this as a new first clap
                    self.state.first_clap_time = now
        return False

    def detect(self, rms_stream: Generator[float, None, None]) -> Generator[float, None, None]:
        """
        Consume an RMS stream and yield double-clap gaps.
        """
        for level in rms_stream:
            if self.update(level):
                yield self.last_gap