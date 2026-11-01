"""Bad Apple!! cinematic player for the secret Caro stage."""

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
import zlib

import pygame

from bloxorz_solver.game.state import Level
from bloxorz_solver.levels.loader import parse_level

WIDTH = 28
HEIGHT = 20
FPS = 15.0
TOTAL_FRAMES = 3287
BYTES_PER_FRAME = (WIDTH * HEIGHT + 7) // 8  # 70 bytes


def load_secret_level() -> Level:
    """Load the hidden 11_bad_apple Caro stage."""
    data = files("bloxorz_solver.bad_apple").joinpath("secret_level.json").read_text(encoding="utf-8")
    import json
    return parse_level(json.loads(data))


@dataclass
class CinematicState:
    active: bool = False
    elapsed_time: float = 0.0
    current_frame: int = 0
    zoom_progress: float = 0.0  # 0.0 (normal) to 1.0 (fully zoomed out)


class BadApplePlayer:
    """Streams monochrome frames synchronized with the chiptune audio."""

    def __init__(self):
        self._raw_frames: bytes | None = None
        self._audio_path: Path | None = None
        self._sound: pygame.mixer.Sound | None = None
        self._channel: pygame.mixer.Channel | None = None
        self.state = CinematicState()

    def _ensure_loaded(self) -> None:
        if self._raw_frames is None:
            compressed = files("bloxorz_solver.bad_apple").joinpath("frames.bin").read_bytes()
            self._raw_frames = zlib.decompress(compressed)

        if self._sound is None:
            try:
                if not pygame.mixer.get_init():
                    pygame.mixer.init(44100, -16, 2, 512)
                ogg_bytes = files("bloxorz_solver.bad_apple").joinpath("bad_apple.ogg").read_bytes()
                import io
                self._sound = pygame.mixer.Sound(io.BytesIO(ogg_bytes))
            except Exception:
                self._sound = None

    def start(self) -> None:
        self._ensure_loaded()
        self.state.active = True
        self.state.elapsed_time = 0.0
        self.state.current_frame = 0
        self.state.zoom_progress = 0.0
        if self._sound is not None:
            try:
                self._channel = self._sound.play()
            except Exception:
                self._channel = None

    def stop(self) -> None:
        self.state.active = False
        self.state.zoom_progress = 0.0
        if self._channel is not None:
            try:
                self._channel.stop()
            except Exception:
                pass
            self._channel = None

    def toggle(self) -> bool:
        if self.state.active:
            self.stop()
            return False
        self.start()
        return True

    def update(self, dt: float) -> None:
        if not self.state.active:
            return

        self.state.elapsed_time += dt
        # Smoothly zoom out over 1.8 seconds
        if self.state.zoom_progress < 1.0:
            self.state.zoom_progress = min(1.0, self.state.zoom_progress + dt / 1.8)

        # Advance frame based on audio or elapsed time
        target_frame = int(self.state.elapsed_time * FPS)
        if target_frame >= TOTAL_FRAMES:
            self.stop()
            return

        self.state.current_frame = target_frame

    def get_frame_matrix(self) -> list[list[int]]:
        """Return 2D grid [row][col] where 1 is white (silhouette) and 0 is black."""
        if not self.state.active or self._raw_frames is None:
            return [[0] * WIDTH for _ in range(HEIGHT)]

        frame_idx = min(self.state.current_frame, TOTAL_FRAMES - 1)
        offset = frame_idx * BYTES_PER_FRAME
        frame_bytes = self._raw_frames[offset : offset + BYTES_PER_FRAME]

        matrix = []
        bit_pos = 0
        for _ in range(HEIGHT):
            row = []
            for _ in range(WIDTH):
                byte_val = frame_bytes[bit_pos >> 3]
                bit = (byte_val >> (7 - (bit_pos & 7))) & 1
                row.append(bit)
                bit_pos += 1
            matrix.append(row)
        return matrix
