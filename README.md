# TeslaMate to Traccar Bridge

A lightweight Docker service that subscribes to [TeslaMate](https://github.com/teslamate-org/teslamate)'s
MQTT topics and forwards real-time GPS/telemetry data to [Traccar](https://www.traccar.org/)
via the OsmAnd protocol (HTTP on port 5055).

Also includes a one-time import script to backfill historical TeslaMate
positions into Traccar.

## How It Works

```
TeslaMate  ──MQTT──▶  Mosquitto  ──subscribe──▶  Bridge  ──HTTP──▶  Traccar (OsmAnd :5055)
```

TeslaMate publishes vehicle telemetry to MQTT topics like
`teslamate/cars/<car_id>/latitude`. The bridge subscribes to these topics,
accumulates the latest values, and sends position updates to Traccar's OsmAnd
endpoint as simple HTTP requests.

**While driving**, every position update is forwarded immediately.
**While parked**, updates are sent at a configurable interval (default 30s).

### Data forwarded

| TeslaMate topic | Traccar field |
|---|---|
| `latitude` / `longitude` | `lat` / `lon` |
| `speed` | `speed` (converted from km/h to knots) |
| `heading` | `bearing` |
| `elevation` | `altitude` |
| `battery_level` | `batt` (stored as `batteryLevel` attribute) |
| `odometer` | `odometer` (custom attribute) |
| `power` | `power` (custom attribute) |
| `charging_state` | `charge` (native Traccar boolean: `true` when charging) |
| `plugged_in` | `pluggedIn` (custom attribute) |

## Quick Start

### 1. Create a device in Traccar

1. Open the Traccar web UI.
2. Click **+** to add a new device.
3. Set **Name** to something recognizable (e.g. `My Tesla`).
4. Set **Identifier** to a stable string (e.g. `tesla-model-y` or the VIN).
   This value must match the `DEVICE_ID` environment variable.
5. Optionally set **Category** to `car`.
6. Save.

### 2. Add the service to your Docker Compose

See [`docker-compose.example.yml`](docker-compose.example.yml) for a complete
example. The key requirement is that the bridge container can reach both the
Mosquitto broker and Traccar's OsmAnd port.

```yaml
teslamate_traccar:
  image: ghcr.io/jasonwaters/teslamate-to-traccar-bridge:latest
  container_name: teslamate_traccar
  restart: unless-stopped
  networks:
    - teslamate_net   # to reach Mosquitto
    - traccar_net     # to reach Traccar
  depends_on:
    - teslamate_mosquitto
    - traccar
  environment:
    - MQTT_HOST=teslamate_mosquitto
    - TRACCAR_HOST=traccar
    - TRACCAR_PORT=5055
    - DEVICE_ID=tesla-model-y    # must match the Traccar device identifier
    - CAR_ID=1                   # TeslaMate car ID
```

### 3. Start

```bash
docker compose up -d teslamate_traccar
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MQTT_HOST` | `teslamate_mosquitto` | Mosquitto broker hostname |
| `MQTT_PORT` | `1883` | Mosquitto broker port |
| `TRACCAR_HOST` | `traccar` | Traccar server hostname |
| `TRACCAR_PORT` | `5055` | Traccar OsmAnd protocol port |
| `DEVICE_ID` | *(required)* | Traccar device identifier |
| `CAR_ID` | `1` | TeslaMate car ID |
| `UPDATE_INTERVAL` | `30` | Min seconds between position updates when not driving |
| `LOG_LEVEL` | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## Historical Import

To backfill historical positions from TeslaMate's database into Traccar:

```bash
docker compose run --rm teslamate_traccar python import_history.py
```

This reads the TeslaMate `positions` table and replays each position through
Traccar's OsmAnd endpoint with the original timestamp. Traccar's duplicate
filter prevents double-imports, so the script is safe to re-run.

Consecutive stationary positions at the same coordinates are skipped by default
to reduce volume.

### Import environment variables

| Variable | Default | Description |
|---|---|---|
| `TESLAMATE_DB_HOST` | `teslamate_database` | TeslaMate Postgres host |
| `TESLAMATE_DB_PORT` | `5432` | TeslaMate Postgres port |
| `TESLAMATE_DB_USER` | `teslamate` | TeslaMate Postgres user |
| `TESLAMATE_DB_PASSWORD` | *(required)* | TeslaMate Postgres password |
| `TESLAMATE_DB_NAME` | `teslamate` | TeslaMate Postgres database |
| `IMPORT_SINCE` | `2026-01-01` | Import positions from this date onward (YYYY-MM-DD) |
| `BATCH_SIZE` | `500` | Rows fetched per DB query batch |
| `REQUEST_DELAY` | `0.005` | Seconds between OsmAnd HTTP requests |
| `SKIP_STATIONARY_DUPLICATES` | `true` | Skip consecutive parked positions at same coordinates |

## License

[MIT](LICENSE)
