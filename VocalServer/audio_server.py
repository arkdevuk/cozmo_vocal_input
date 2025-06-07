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
import soundfile as sf
from tempfile import NamedTemporaryFile

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

listening = False  # Global flag

async def handle_connection(websocket):
    global listening
    print("[AudioServer] Client connected.")
    buffer = b""
    whisper_audio = bytearray()
    silence_threshold = 500  # Amplitude below which we consider silence
    silence_duration = 1.5  # Seconds of silence before auto-stop
    max_listen_duration = 10  # Maximum allowed listening time in seconds

    silence_start_time = None
    listening_start_time = None

    try:
        async for message in websocket:
            buffer += message
            frame_size = porcupine.frame_length if porcupine else 512
            frame_bytes = frame_size * 2  # 2 bytes/sample

            while len(buffer) >= frame_bytes:
                frame = buffer[:frame_bytes]
                buffer = buffer[frame_bytes:]
                pcm = np.frombuffer(frame, dtype=np.int16)

                # Wake word detection
                if porcupine and porcupine.process(pcm) >= 0:
                    Logger.info("[AudioServer] Wake word detected.")
                    json_as_string = json.dumps({
                        "event": "wake_word_detected",
                        "stamp": time.monotonic()
                    })
                    mqtt_client.publish("cozmo/audio_input/wake_word", json_as_string)

                # If we're listening, buffer audio and check for silence
                if listening:
                    whisper_audio += frame

                    if listening_start_time is None:
                        listening_start_time = time.monotonic()

                    energy = np.abs(pcm).mean()
                    if energy < silence_threshold:
                        if silence_start_time is None:
                            silence_start_time = time.monotonic()
                        elif time.monotonic() - silence_start_time > silence_duration:
                            print("[AudioServer] Silence detected. Ending listening.")
                            listening = False
                    else:
                        silence_start_time = None

                    if time.monotonic() - listening_start_time > max_listen_duration:
                        print("[AudioServer] Timeout reached. Ending listening.")
                        listening = False

                # Handle stop condition
                if not listening and whisper_audio:
                    with NamedTemporaryFile(suffix=".wav", delete=False) as tmpfile:
                        sf.write(tmpfile.name, np.frombuffer(whisper_audio, dtype=np.int16), 16000, 'PCM_16')
                        result = whisper_model.transcribe(tmpfile.name)
                        mqtt_client.publish("cozmo/audio_input/transcription", {
                            "event": "speech_transcribed",
                            "text": result['text'],
                            "stamp": time.monotonic()
                        })
                        whisper_audio.clear()
                    # Reset timers
                    listening_start_time = None
                    silence_start_time = None

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