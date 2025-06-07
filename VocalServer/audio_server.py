# VocalServer/audio_server.py
import asyncio
import json
import os
import time

import numpy as np
import torch
import websockets
import pvporcupine

from Logger import Logger
from MQTTClient import mqtt_client

import whisper

device = "cuda" if torch.cuda.is_available() else "cpu"
whisper_model = whisper.load_model("base", device=device)


try:
    porcupine = pvporcupine.create(
        access_key= os.environ.get("PICOVOICE_ACCESS_KEY", None),
        keyword_paths=['./models/Cosmo_fr_linux_v3_0_0.ppn'],
        model_path='./models/porcupine_params_fr.pv'
    )
    print("[AudioServer] Porcupine initialized.")
except ImportError:
    porcupine = None
    print("[AudioServer] Porcupine not installed.")

HOST = "0.0.0.0"
PORT = 8797
PATH = "/audio"

async def handle_connection(websocket):
    print("[AudioServer] Client connected.")
    print("[AudioServer] Client connected.")
    buffer = b""

    try:
        async for message in websocket:
            buffer += message
            frame_size = porcupine.frame_length if porcupine else 512
            frame_bytes = frame_size * 2  # 2 bytes per sample (16-bit PCM)

            while len(buffer) >= frame_bytes:
                frame = buffer[:frame_bytes]
                buffer = buffer[frame_bytes:]
                pcm = np.frombuffer(frame, dtype=np.int16)
                # we always check for the wake word if not listening
                if porcupine and porcupine.process(pcm) >= 0:
                    mqtt_client.publish(f"cozmo/audio_input/wake_word", {
                        "event": "wake_word_detected",
                        "stamp": time.monotonic()
                    })

    except websockets.exceptions.ConnectionClosed:
        print("[AudioServer] Client disconnected unexpectedly.")

async def start_server():
    print(f"[AudioServer] Starting WebSocket server on ws://{HOST}:{PORT}{PATH}")
    async with websockets.serve(handle_connection, HOST, PORT) as server:
        await server.serve_forever()

def handle_events(client, data):
    # message is expected to be a JSON string
    try:
        data = json.loads(data)
    except json.JSONDecodeError:
        Logger.error(f"Invalid JSON data: {data}")
        return
    # TODO > if we get the event to start listening, we stop checking for the wake word and start listening to the audio stream to process it with Whisper/OpenAI
    if data.get("event") == "start_listening":
        pass # TODO

def run_audio_server():
    mqtt_client.subscribe(f"cozmo/voice_input/events", handle_events)
    asyncio.run(start_server())