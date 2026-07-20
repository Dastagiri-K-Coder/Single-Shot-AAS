# -*- coding: utf-8 -*-
"""
voice_trigger.py — Offline voice command listener.

Listens continuously for the trigger phrase (default: "take attendance")
using Vosk — a fully offline speech recognition engine.
No internet required. Works on Raspberry Pi, laptops, and mini PCs.

Why Vosk (not Google Speech API)?
    - Fully offline — works even without internet in the classroom
    - Lightweight (~40MB model vs cloud dependency)
    - Low latency on Raspberry Pi 4
    - No API key or billing needed

Setup (one-time):
    1. Download the Vosk model:
       wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
       unzip vosk-model-small-en-us-0.15.zip -d <repo-root>/vosk-model-small-en-us

    2. Install dependencies:
       pip install vosk sounddevice

    3. Run:
       python main.py --voice

Functions:
    listen_for_trigger(callback)  → blocking loop, calls callback() on trigger phrase
    test_microphone()             → quick check that mic is working
"""

import json
import queue
import os
import threading

from aas.core.config import VOICE_TRIGGER_PHRASE, VOSK_MODEL_PATH

# Lazy imports — only loaded when voice mode is activated
# This prevents import errors if vosk/sounddevice are not installed
# for users who don't need the voice feature.
def _import_vosk():
    try:
        from vosk import Model, KaldiRecognizer
        return Model, KaldiRecognizer
    except ImportError:
        raise ImportError(
            "Vosk is not installed. Run:\n"
            "    pip install vosk sounddevice\n"
            "Then download the model:\n"
            "    wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip\n"
            "    unzip vosk-model-small-en-us-0.15.zip -d ../vosk-model-small-en-us"
        )

def _import_sounddevice():
    try:
        import sounddevice as sd
        return sd
    except ImportError:
        raise ImportError(
            "sounddevice is not installed. Run:\n"
            "    pip install sounddevice\n"
            "Linux also needs: sudo apt install portaudio19-dev"
        )


_SAMPLE_RATE = 16000    # Hz — required by Vosk small-en-us model
_BLOCK_SIZE  = 8000     # samples per audio block


def listen_for_trigger(on_trigger_callback: callable,
                       run_once: bool = False) -> None:
    """
    Blocking function that listens for the voice trigger phrase.

    When the phrase is detected, calls on_trigger_callback() in a
    separate thread so audio capture isn't interrupted.

    Args:
        on_trigger_callback : Zero-argument callable. Called on trigger.
        run_once            : If True, stop after first trigger (for testing).

    Example:
        def take_attendance():
            path = capture.capture_single_shot()
            recognition.run_recognition(path)

        listen_for_trigger(take_attendance)
    """
    Model, KaldiRecognizer = _import_vosk()
    sd = _import_sounddevice()

    # Validate model path
    if not os.path.isdir(VOSK_MODEL_PATH):
        raise FileNotFoundError(
            f"Vosk model not found at: {VOSK_MODEL_PATH}\n\n"
            "Download it with:\n"
            "    wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip\n"
            f"    unzip vosk-model-small-en-us-0.15.zip -d {VOSK_MODEL_PATH}\n"
        )

    print(f"Loading Vosk model from: {VOSK_MODEL_PATH}")
    model = Model(VOSK_MODEL_PATH)
    rec   = KaldiRecognizer(model, _SAMPLE_RATE)

    audio_queue = queue.Queue()

    def audio_callback(indata, frames, time, status):
        """Called by sounddevice on each audio block."""
        if status:
            print(f"  [Audio] {status}")
        audio_queue.put(bytes(indata))

    print(f"\n🎙️  Voice trigger active.")
    print(f"    Listening for: \"{VOICE_TRIGGER_PHRASE}\"")
    print(f"    Press Ctrl+C to stop.\n")

    with sd.RawInputStream(
        samplerate=_SAMPLE_RATE,
        blocksize=_BLOCK_SIZE,
        dtype='int16',
        channels=1,
        callback=audio_callback
    ):
        triggered = False
        while not (run_once and triggered):
            data = audio_queue.get()

            if rec.AcceptWaveform(data):
                result_json = json.loads(rec.Result())
                text = result_json.get("text", "").lower().strip()

                if text:
                    print(f"  Heard: \"{text}\"")

                if VOICE_TRIGGER_PHRASE in text:
                    print(f"\n  ✅ Trigger detected! Launching attendance capture ...\n")
                    triggered = True
                    # Run in background thread so audio loop isn't blocked
                    t = threading.Thread(target=on_trigger_callback, daemon=True)
                    t.start()

            else:
                # Partial result — useful for debugging
                partial = json.loads(rec.PartialResult()).get("partial", "")
                if partial and len(partial) > 3:
                    print(f"  ... {partial}", end='\r')


def test_microphone(duration_seconds: int = 5) -> None:
    """
    Quick test: print everything heard for N seconds.
    Run this first to confirm the microphone is working.

    Usage:
        python -c "from voice_trigger import test_microphone; test_microphone()"
    """
    Model, KaldiRecognizer = _import_vosk()
    sd = _import_sounddevice()

    if not os.path.isdir(VOSK_MODEL_PATH):
        print(f"[ERROR] Vosk model not found at: {VOSK_MODEL_PATH}")
        return

    model = Model(VOSK_MODEL_PATH)
    rec   = KaldiRecognizer(model, _SAMPLE_RATE)
    q     = queue.Queue()

    def cb(indata, frames, time, status):
        q.put(bytes(indata))

    print(f"🎙️  Microphone test — speak for {duration_seconds} seconds ...")
    import time as _time
    start = _time.time()

    with sd.RawInputStream(samplerate=_SAMPLE_RATE, blocksize=_BLOCK_SIZE,
                           dtype='int16', channels=1, callback=cb):
        while _time.time() - start < duration_seconds:
            data = q.get()
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result()).get("text", "")
                if result:
                    print(f"  Recognized: \"{result}\"")

    print("  Microphone test complete.")
