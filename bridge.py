#!/usr/bin/env python3
"""TeslaMate MQTT -> Traccar OsmAnd bridge.

Subscribes to TeslaMate's MQTT topics for a single car and forwards
position updates to Traccar via the OsmAnd HTTP protocol.
"""

import logging
import os
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError

import paho.mqtt.client as mqtt

log = logging.getLogger("teslamate-traccar")

MQTT_HOST = os.environ.get("MQTT_HOST", "teslamate_mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
TRACCAR_HOST = os.environ.get("TRACCAR_HOST", "traccar")
TRACCAR_PORT = int(os.environ.get("TRACCAR_PORT", "5055"))
DEVICE_ID = os.environ.get("DEVICE_ID", "")
CAR_ID = os.environ.get("CAR_ID", "1")
UPDATE_INTERVAL = int(os.environ.get("UPDATE_INTERVAL", "30"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

TRACKED_TOPICS = [
    "latitude",
    "longitude",
    "speed",
    "heading",
    "elevation",
    "battery_level",
    "odometer",
    "power",
    "state",
    "since",
]

TRACCAR_URL = f"http://{TRACCAR_HOST}:{TRACCAR_PORT}"


class CarState:
    """Accumulates the latest MQTT values for one car."""

    def __init__(self):
        self.values: dict[str, str] = {}
        self.last_sent: float = 0.0

    def update(self, topic: str, payload: str) -> None:
        self.values[topic] = payload

    @property
    def has_position(self) -> bool:
        return "latitude" in self.values and "longitude" in self.values

    @property
    def is_driving(self) -> bool:
        return self.values.get("state", "").lower() == "driving"

    def should_send(self) -> bool:
        if not self.has_position:
            return False
        if self.is_driving:
            return True
        return (time.time() - self.last_sent) >= UPDATE_INTERVAL

    def build_params(self) -> dict[str, str]:
        v = self.values
        params: dict[str, str] = {
            "id": DEVICE_ID,
            "lat": v["latitude"],
            "lon": v["longitude"],
            "timestamp": str(int(time.time())),
        }
        if "speed" in v and v["speed"]:
            try:
                kmh = float(v["speed"])
                params["speed"] = f"{kmh / 1.852:.4f}"  # km/h -> knots
            except ValueError:
                pass
        if "heading" in v and v["heading"]:
            params["bearing"] = v["heading"]
        if "elevation" in v and v["elevation"]:
            params["altitude"] = v["elevation"]
        if "battery_level" in v and v["battery_level"]:
            params["batt"] = v["battery_level"]
        if "odometer" in v and v["odometer"]:
            try:
                params["odometer"] = f"{float(v['odometer']) * 1000:.0f}"  # km -> m
            except ValueError:
                pass
        if "power" in v and v["power"]:
            params["power"] = v["power"]
        return params

    def mark_sent(self) -> None:
        self.last_sent = time.time()


car_state = CarState()


def send_to_traccar(params: dict[str, str]) -> bool:
    url = f"{TRACCAR_URL}/?{urlencode(params)}"
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=10) as resp:
            status = resp.status
        if status == 200:
            log.debug("Sent position: lat=%s lon=%s", params["lat"], params["lon"])
            return True
        log.warning("Traccar returned HTTP %d for %s", status, url)
        return False
    except URLError as exc:
        log.error("Failed to send to Traccar: %s", exc)
        return False


def on_connect(client: mqtt.Client, _userdata, _flags, rc, _properties=None):
    if rc != 0:
        log.error("MQTT connect failed: rc=%d", rc)
        return
    log.info("Connected to MQTT broker at %s:%d", MQTT_HOST, MQTT_PORT)
    topic = f"teslamate/cars/{CAR_ID}/+"
    client.subscribe(topic)
    log.info("Subscribed to %s", topic)


def on_message(_client: mqtt.Client, _userdata, msg: mqtt.MQTTMessage):
    parts = msg.topic.split("/")
    if len(parts) != 4:
        return
    field = parts[3]
    if field not in TRACKED_TOPICS:
        return

    payload = msg.payload.decode("utf-8", errors="replace").strip()
    if not payload:
        return

    car_state.update(field, payload)

    if field in ("latitude", "longitude") and car_state.should_send():
        params = car_state.build_params()
        if send_to_traccar(params):
            car_state.mark_sent()


def on_disconnect(_client, _userdata, rc, _properties=None):
    if rc != 0:
        log.warning("Unexpected MQTT disconnect (rc=%d), will reconnect", rc)


def main():
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    if not DEVICE_ID:
        log.error("DEVICE_ID environment variable is required")
        sys.exit(1)

    log.info(
        "Starting TeslaMate->Traccar bridge: car_id=%s device_id=%s traccar=%s:%d",
        CAR_ID, DEVICE_ID, TRACCAR_HOST, TRACCAR_PORT,
    )

    client = mqtt.Client(
        client_id=f"teslamate-traccar-{CAR_ID}",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=60)

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
