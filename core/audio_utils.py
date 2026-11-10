"""MAYERA - PCM audio helpers.

Gemini Live speaks exactly two formats:
  * input  : PCM signed 16-bit little-endian, 16000 Hz, mono
  * output : PCM signed 16-bit little-endian, 24000 Hz, mono

Rules that keep the classic bugs away:
  * Audio is handled as `bytes` end to end. Nothing here ever calls
    .encode() on audio - if a `str` sneaks in by mistake it is rejected,
    not silently converted.
  * Resampling is linear interpolation on int16 samples (pure stdlib).
"""

import math
import struct

SAMPLE_WIDTH = 2  # bytes per int16 sample


def ensure_bytes(data, what="audio"):
    """Return data if it is bytes-like, else raise a clear error."""
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    raise TypeError(
        f"{what} must be bytes, got {type(data).__name__}. "
        "Audio data must never be passed as str."
    )


def pcm16_to_floats(data):
    """PCM16 LE bytes -> list of floats in [-1.0, 1.0]."""
    data = ensure_bytes(data)
    count = len(data) // SAMPLE_WIDTH
    ints = struct.unpack("<%dh" % count, data[: count * SAMPLE_WIDTH])
    return [v / 32768.0 for v in ints]


def floats_to_pcm16(values):
    """Floats in [-1.0, 1.0] -> PCM16 LE bytes (clamped, no wrap-around)."""
    out = bytearray()
    for v in values:
        if v > 1.0:
            v = 1.0
        elif v < -1.0:
            v = -1.0
        out += struct.pack("<h", int(round(v * 32767)))
    return bytes(out)


def resample_pcm16(data, from_rate, to_rate):
    """Resample PCM16 mono audio with linear interpolation."""
    data = ensure_bytes(data)
    if from_rate == to_rate or not data:
        return data
    samples = pcm16_to_floats(data)
    if not samples:
        return b""
    ratio = from_rate / float(to_rate)
    out_len = int(len(samples) / ratio)
    out = []
    for i in range(out_len):
        pos = i * ratio
        lo = int(math.floor(pos))
        hi = min(lo + 1, len(samples) - 1)
        frac = pos - lo
        out.append(samples[lo] * (1.0 - frac) + samples[hi] * frac)
    return floats_to_pcm16(out)


def rms_level(data):
    """Root-mean-square level of PCM16 audio, 0.0 (silent) .. 1.0 (loud).

    Speed (v3.0): this runs on EVERY microphone chunk in the hot path
    before the chunk is forwarded, so it works on the raw int16 values
    (no float list) and, for long chunks, samples every 4th sample -
    statistically the same level for speech, ~4x less CPU.
    """
    data = ensure_bytes(data)
    if len(data) < SAMPLE_WIDTH:
        return 0.0
    count = len(data) // SAMPLE_WIDTH
    ints = struct.unpack("<%dh" % count, data[: count * SAMPLE_WIDTH])
    step = 4 if count > 512 else 1
    total = 0
    n = 0
    for i in range(0, count, step):
        v = ints[i]
        total += v * v
        n += 1
    if not n:
        return 0.0
    return math.sqrt(total / n) / 32768.0


def should_forward_mic(level, last_ai, now, window=1.2, loud=0.22):
    """Noise gate for while JARVIS himself is speaking (v3.23).

    The user's report: while JARVIS is mid-sentence, any background
    sound (TV, family talking, a door) reaches Gemini, its VAD
    calls it an interruption, and JARVIS stops and never finishes
    the sentence. The browser already ducks the mic x0.35 during
    playback (v3.10); this server-side gate is the hard version:
    while JARVIS audio arrived within the last `window` seconds,
    only genuinely LOUD chunks (level >= loud - the user clearly
    talking over him, a real barge-in or Stop) are forwarded.
    Quiet chunks in that window are dropped, so background noise
    can no longer cut him off. Outside the window everything is
    forwarded exactly as before.
    """
    if not last_ai:
        return True
    if now - last_ai > window:
        return True
    return level >= loud


def chunk_bytes(data, chunk_size):
    """Yield successive chunks of `chunk_size` bytes."""
    data = ensure_bytes(data)
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]
