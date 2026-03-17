"""Tests for the real-time MQTT-to-Traccar bridge."""

import time
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import bridge


class TestCarState:
    def _make(self):
        return bridge.CarState()

    def test_empty_state_has_no_position(self):
        cs = self._make()
        assert not cs.has_position

    def test_has_position_requires_both_lat_and_lon(self):
        cs = self._make()
        cs.update("latitude", "40.377")
        assert not cs.has_position
        cs.update("longitude", "-111.768")
        assert cs.has_position

    def test_is_driving(self):
        cs = self._make()
        assert not cs.is_driving
        cs.update("state", "online")
        assert not cs.is_driving
        cs.update("state", "driving")
        assert cs.is_driving
        cs.update("state", "Driving")
        assert cs.is_driving

    def test_should_send_requires_position(self):
        cs = self._make()
        cs.update("state", "driving")
        assert not cs.should_send()

    def test_should_send_always_when_driving(self):
        cs = self._make()
        cs.update("latitude", "40.0")
        cs.update("longitude", "-111.0")
        cs.update("state", "driving")
        cs.mark_sent()
        assert cs.should_send()

    def test_should_send_respects_interval_when_parked(self):
        cs = self._make()
        cs.update("latitude", "40.0")
        cs.update("longitude", "-111.0")
        cs.update("state", "online")
        cs.mark_sent()
        assert not cs.should_send()

    def test_should_send_after_interval_elapsed(self):
        cs = self._make()
        cs.update("latitude", "40.0")
        cs.update("longitude", "-111.0")
        cs.update("state", "online")
        cs.last_sent = time.time() - bridge.UPDATE_INTERVAL - 1
        assert cs.should_send()

    def test_build_params_minimal(self):
        cs = self._make()
        cs.update("latitude", "40.377101")
        cs.update("longitude", "-111.768063")
        with patch.object(bridge, "DEVICE_ID", "test-device"):
            params = cs.build_params()
        assert params["id"] == "test-device"
        assert params["lat"] == "40.377101"
        assert params["lon"] == "-111.768063"
        assert "timestamp" in params

    def test_build_params_speed_conversion(self):
        """Speed should be converted from km/h to knots."""
        cs = self._make()
        cs.update("latitude", "40.0")
        cs.update("longitude", "-111.0")
        cs.update("speed", "100")
        with patch.object(bridge, "DEVICE_ID", "x"):
            params = cs.build_params()
        knots = float(params["speed"])
        assert abs(knots - 100 / 1.852) < 0.01

    def test_build_params_all_fields(self):
        cs = self._make()
        cs.update("latitude", "40.0")
        cs.update("longitude", "-111.0")
        cs.update("speed", "50")
        cs.update("heading", "180")
        cs.update("elevation", "1500")
        cs.update("battery_level", "75")
        cs.update("odometer", "54000.5")
        cs.update("power", "-10")
        with patch.object(bridge, "DEVICE_ID", "x"):
            params = cs.build_params()
        assert params["bearing"] == "180"
        assert params["altitude"] == "1500"
        assert params["batt"] == "75"
        assert params["odometer"] == "54000500"  # km -> m
        assert params["power"] == "-10"

    def test_build_params_skips_empty_optional_fields(self):
        cs = self._make()
        cs.update("latitude", "40.0")
        cs.update("longitude", "-111.0")
        cs.update("speed", "")
        cs.update("heading", "")
        with patch.object(bridge, "DEVICE_ID", "x"):
            params = cs.build_params()
        assert "speed" not in params
        assert "bearing" not in params

    def test_build_params_invalid_speed_ignored(self):
        cs = self._make()
        cs.update("latitude", "40.0")
        cs.update("longitude", "-111.0")
        cs.update("speed", "not-a-number")
        with patch.object(bridge, "DEVICE_ID", "x"):
            params = cs.build_params()
        assert "speed" not in params


class TestOnMessage:
    def _msg(self, topic, payload):
        msg = MagicMock()
        msg.topic = topic
        msg.payload = payload.encode("utf-8")
        return msg

    def setup_method(self):
        bridge.car_state = bridge.CarState()

    def test_ignores_untracked_topic(self):
        bridge.on_message(None, None, self._msg("teslamate/cars/1/model", "Y"))
        assert bridge.car_state.values == {}

    def test_ignores_wrong_topic_depth(self):
        bridge.on_message(None, None, self._msg("teslamate/cars/1/foo/bar", "x"))
        assert bridge.car_state.values == {}

    def test_ignores_empty_payload(self):
        bridge.on_message(None, None, self._msg("teslamate/cars/1/latitude", ""))
        assert "latitude" not in bridge.car_state.values

    def test_updates_state_on_valid_message(self):
        bridge.on_message(None, None, self._msg("teslamate/cars/1/latitude", "40.0"))
        assert bridge.car_state.values["latitude"] == "40.0"

    @patch("bridge.send_to_traccar", return_value=True)
    def test_sends_on_lat_update_when_ready(self, mock_send):
        cs = bridge.car_state
        cs.update("longitude", "-111.0")
        cs.update("state", "driving")
        with patch.object(bridge, "DEVICE_ID", "test"):
            bridge.on_message(None, None, self._msg("teslamate/cars/1/latitude", "40.0"))
        mock_send.assert_called_once()
        assert cs.last_sent > 0

    @patch("bridge.send_to_traccar", return_value=True)
    def test_no_send_on_non_position_topic(self, mock_send):
        cs = bridge.car_state
        cs.update("latitude", "40.0")
        cs.update("longitude", "-111.0")
        cs.update("state", "driving")
        with patch.object(bridge, "DEVICE_ID", "test"):
            bridge.on_message(None, None, self._msg("teslamate/cars/1/speed", "50"))
        mock_send.assert_not_called()
