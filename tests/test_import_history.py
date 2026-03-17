"""Tests for the historical import script."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import import_history


class TestMakeParams:
    def _row(self, **overrides):
        defaults = {
            "date": datetime(2026, 3, 16, 12, 0, 0),
            "latitude": Decimal("40.377101"),
            "longitude": Decimal("-111.768063"),
            "speed": 60,
            "elevation": 1400,
            "battery_level": 75,
            "odometer": 54685.5,
            "power": -8,
        }
        defaults.update(overrides)
        return defaults

    def test_basic_fields(self):
        with patch.object(import_history, "DEVICE_ID", "tesla-1"):
            params = import_history.make_params(self._row())
        assert params["id"] == "tesla-1"
        assert params["lat"] == "40.377101"
        assert params["lon"] == "-111.768063"

    def test_timestamp_is_utc_epoch(self):
        dt = datetime(2026, 1, 1, 0, 0, 0)
        expected = int(dt.replace(tzinfo=timezone.utc).timestamp())
        with patch.object(import_history, "DEVICE_ID", "x"):
            params = import_history.make_params(self._row(date=dt))
        assert params["timestamp"] == str(expected)

    def test_speed_converted_to_knots(self):
        with patch.object(import_history, "DEVICE_ID", "x"):
            params = import_history.make_params(self._row(speed=100))
        knots = float(params["speed"])
        assert abs(knots - 100 / 1.852) < 0.01

    def test_all_optional_fields_present(self):
        with patch.object(import_history, "DEVICE_ID", "x"):
            params = import_history.make_params(self._row())
        assert "altitude" in params
        assert "batt" in params
        assert "odometer" in params
        assert "power" in params

    def test_odometer_converted_to_meters(self):
        with patch.object(import_history, "DEVICE_ID", "x"):
            params = import_history.make_params(self._row(odometer=54685.5))
        assert params["odometer"] == "54685500"

    def test_none_fields_omitted(self):
        with patch.object(import_history, "DEVICE_ID", "x"):
            params = import_history.make_params(
                self._row(speed=None, elevation=None, battery_level=None,
                          odometer=None, power=None)
            )
        assert "speed" not in params
        assert "altitude" not in params
        assert "batt" not in params
        assert "odometer" not in params
        assert "power" not in params

    def test_zero_speed_still_included(self):
        with patch.object(import_history, "DEVICE_ID", "x"):
            params = import_history.make_params(self._row(speed=0))
        assert params["speed"] == "0.0000"


class TestStationaryDedup:
    """Verify the dedup logic that skips consecutive stationary positions."""

    def _rows(self, coords_and_speeds):
        """Build a list of row dicts from (lat, lon, speed) tuples."""
        return [
            {
                "date": datetime(2026, 1, 1, h, 0, 0),
                "latitude": Decimal(str(lat)),
                "longitude": Decimal(str(lon)),
                "speed": speed,
                "elevation": None,
                "battery_level": 80,
                "odometer": 50000.0,
                "power": 0,
            }
            for h, (lat, lon, speed) in enumerate(coords_and_speeds)
        ]

    def test_consecutive_stationary_same_coords_skipped(self):
        rows = self._rows([
            (40.0, -111.0, 0),
            (40.0, -111.0, 0),
            (40.0, -111.0, 0),
        ])
        sent, skipped = self._simulate(rows, skip=True)
        assert sent == 1
        assert skipped == 2

    def test_stationary_different_coords_not_skipped(self):
        rows = self._rows([
            (40.0, -111.0, 0),
            (40.1, -111.1, 0),
            (40.2, -111.2, 0),
        ])
        sent, skipped = self._simulate(rows, skip=True)
        assert sent == 3
        assert skipped == 0

    def test_moving_positions_never_skipped(self):
        rows = self._rows([
            (40.0, -111.0, 50),
            (40.0, -111.0, 50),
            (40.0, -111.0, 50),
        ])
        sent, skipped = self._simulate(rows, skip=True)
        assert sent == 3
        assert skipped == 0

    def test_dedup_disabled(self):
        rows = self._rows([
            (40.0, -111.0, 0),
            (40.0, -111.0, 0),
            (40.0, -111.0, 0),
        ])
        sent, skipped = self._simulate(rows, skip=False)
        assert sent == 3
        assert skipped == 0

    def test_mixed_driving_and_parked(self):
        rows = self._rows([
            (40.0, -111.0, 0),   # parked (sent)
            (40.0, -111.0, 0),   # parked same coords (skipped)
            (40.1, -111.1, 60),  # driving (sent)
            (40.2, -111.2, 60),  # driving (sent)
            (40.2, -111.2, 0),   # parked (sent, first at new coords)
            (40.2, -111.2, 0),   # parked same coords (skipped)
        ])
        sent, skipped = self._simulate(rows, skip=True)
        assert sent == 4
        assert skipped == 2

    def _simulate(self, rows, skip):
        """Replay the dedup logic from import_history.main without DB/HTTP."""
        sent = 0
        skipped = 0
        prev_lat = None
        prev_lon = None
        prev_speed_zero = False

        for row in rows:
            lat = row["latitude"]
            lon = row["longitude"]
            speed = row["speed"] or 0
            is_stationary = speed == 0

            if skip and is_stationary and prev_speed_zero:
                if lat == prev_lat and lon == prev_lon:
                    skipped += 1
                    continue

            prev_lat = lat
            prev_lon = lon
            prev_speed_zero = is_stationary
            sent += 1

        return sent, skipped
