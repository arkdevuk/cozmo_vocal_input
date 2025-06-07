import os
import threading
import time

from dotenv import load_dotenv, find_dotenv

from Logger import Logger
from MQTTClient import mqtt_client

# --- Load environment variables ---
load_dotenv(dotenv_path=find_dotenv(".env"), override=False)
local_env = find_dotenv(".env.local")
if local_env:
    load_dotenv(dotenv_path=local_env, override=True)

from VocalServer import run_audio_server

def init_broker():
    mqtt_client.set_config(
        broker=os.environ.get("MQTT_BROKER", "localhost"),
        port=int(os.environ.get("MQTT_PORT", 1884)),
        username=os.environ.get("MQTT_USERNAME", 'username'),
        password=os.environ.get("MQTT_PASSWORD", 'password'),
    )
    mqtt_client.start()
    mqtt_client.wait_for_broker_ready(timeout=10)

def vocal_input_handler():
    run_audio_server()

if __name__ == '__main__':
    init_broker()
    Logger.info("[Main] Starting vocal input service...")

    threading.Thread(target=vocal_input_handler, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        Logger.info("[Main] Shutting down")
        mqtt_client.stop()

