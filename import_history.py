#!/usr/bin/env python3
"""Import historical TeslaMate positions into Traccar via the OsmAnd protocol.

Reads from the TeslaMate `positions` table and replays each row as an HTTP
request to Traccar's OsmAnd endpoint, preserving the original timestamps.

With ~1.2M rows this takes a while. Progress is printed every 10,000 rows.
The script is idempotent -- Traccar's duplicate filter will drop positions
that have already been imported.
"""

import logging
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError

import psycopg2
import psycopg2.extras

log = logging.getLogger("import-history")

TRACCAR_HOST = os.environ.get("TRACCAR_HOST", "traccar")
TRACCAR_PORT = int(os.environ.get("TRACCAR_PORT", "5055"))
DEVICE_ID = os.environ.get("DEVICE_ID", "")
CAR_ID = int(os.environ.get("CAR_ID", "1"))

DB_HOST = os.environ.get("TESLAMATE_DB_HOST", "teslamate_database")
DB_PORT = int(os.environ.get("TESLAMATE_DB_PORT", "5432"))
DB_USER = os.environ.get("TESLAMATE_DB_USER", "teslamate")
DB_PASS = os.environ.get("TESLAMATE_DB_PASSWORD", "")
DB_NAME = os.environ.get("TESLAMATE_DB_NAME", "teslamate")

IMPORT_SINCE = os.environ.get("IMPORT_SINCE", "2026-01-01")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "500"))
REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "0.005"))
SKIP_STATIONARY_DUPLICATES = os.environ.get("SKIP_STATIONARY_DUPLICATES", "true").lower() == "true"

TRACCAR_URL = f"http://{TRACCAR_HOST}:{TRACCAR_PORT}"

QUERY = """
    SELECT date, latitude, longitude, speed, elevation,
           battery_level, odometer, power
    FROM positions
    WHERE car_id = %s AND date >= %s
    ORDER BY date
"""


def send_position(params: dict[str, str]) -> bool:
    url = f"{TRACCAR_URL}/?{urlencode(params)}"
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except URLError as exc:
        log.warning("HTTP error: %s", exc)
        return False


def make_params(row: dict) -> dict[str, str]:
    dt: datetime = row["date"].replace(tzinfo=timezone.utc)
    params: dict[str, str] = {
        "id": DEVICE_ID,
        "lat": str(row["latitude"]),
        "lon": str(row["longitude"]),
        "timestamp": str(int(dt.timestamp())),
    }
    if row["speed"] is not None:
        params["speed"] = f"{float(row['speed']) / 1.852:.4f}"  # km/h -> knots
    if row["elevation"] is not None:
        params["altitude"] = str(row["elevation"])
    if row["battery_level"] is not None:
        params["batt"] = str(row["battery_level"])
    if row["odometer"] is not None:
        params["odometer"] = str(row["odometer"])
    if row["power"] is not None:
        params["power"] = str(row["power"])
    return params


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    if not DEVICE_ID:
        log.error("DEVICE_ID environment variable is required")
        sys.exit(1)
    if not DB_PASS:
        log.error("TESLAMATE_DB_PASSWORD environment variable is required")
        sys.exit(1)

    log.info(
        "Importing positions: car_id=%d since=%s device_id=%s traccar=%s:%d",
        CAR_ID, IMPORT_SINCE, DEVICE_ID, TRACCAR_HOST, TRACCAR_PORT,
    )
    if SKIP_STATIONARY_DUPLICATES:
        log.info("Skipping consecutive stationary positions with identical coordinates")

    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASS, dbname=DB_NAME,
    )

    sent = 0
    skipped = 0
    errors = 0
    prev_lat = None
    prev_lon = None
    prev_speed_zero = False
    start = time.time()

    with conn.cursor(name="import_cursor", cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.itersize = BATCH_SIZE
        cur.execute(QUERY, (CAR_ID, IMPORT_SINCE))

        for row in cur:
            lat = row["latitude"]
            lon = row["longitude"]
            speed = row["speed"] or 0
            is_stationary = speed == 0

            if SKIP_STATIONARY_DUPLICATES and is_stationary and prev_speed_zero:
                if lat == prev_lat and lon == prev_lon:
                    skipped += 1
                    continue

            prev_lat = lat
            prev_lon = lon
            prev_speed_zero = is_stationary

            params = make_params(row)
            if send_position(params):
                sent += 1
            else:
                errors += 1
                if errors > 50:
                    log.error("Too many errors, aborting")
                    break

            if sent % 10000 == 0 and sent > 0:
                elapsed = time.time() - start
                rate = sent / elapsed
                log.info(
                    "Progress: %d sent, %d skipped, %d errors (%.0f pos/sec)",
                    sent, skipped, errors, rate,
                )

            if REQUEST_DELAY > 0:
                time.sleep(REQUEST_DELAY)

    conn.close()
    elapsed = time.time() - start
    log.info(
        "Done: %d sent, %d skipped, %d errors in %.1f seconds (%.0f pos/sec)",
        sent, skipped, errors, elapsed, sent / max(elapsed, 1),
    )


if __name__ == "__main__":
    main()
