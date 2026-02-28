"""
tests/test_notifier.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for DiscordNotifier.

Uses unittest.mock to avoid real HTTP calls.

Covers:
  - Constructor webhook URL validation
  - send() dry_run path
  - send_text() dry_run path
  - _build_payload() embed structure for BUY and SELL signals
  - _post_with_retry() success (HTTP 204)
  - _post_with_retry() failure after max_retries
  - _post_with_retry() 429 rate-limit handling
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from core.notifier import DiscordNotifier, _BUY_COLOR, _SELL_COLOR
from core.signal_detector import Signal


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

VALID_URL = "https://discord.com/api/webhooks/123456/abcdefg"


def make_signal(direction: str = "BUY", signal_type: str = "tk_cross_up") -> Signal:
    return Signal(
        pair="EURUSD",
        timeframe="H1",
        signal_type=signal_type,
        direction=direction,
        timestamp=datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc),
        price=1.10500,
        details={"tenkan": 1.10500, "kijun": 1.10450, "cloud_top": 1.10200},
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Constructor
# ─────────────────────────────────────────────────────────────────────────────

class TestInit:

    def test_valid_url_accepted(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        assert n.webhook_url == VALID_URL

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Invalid Discord webhook URL"):
            DiscordNotifier(webhook_url="https://example.com/not-a-webhook")

    def test_dry_run_default_false(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        assert n.dry_run is False

    def test_dry_run_can_be_set(self):
        n = DiscordNotifier(webhook_url=VALID_URL, dry_run=True)
        assert n.dry_run is True

    def test_default_max_retries(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        assert n.max_retries == 3


# ─────────────────────────────────────────────────────────────────────────────
#  send() – dry_run
# ─────────────────────────────────────────────────────────────────────────────

class TestSendDryRun:

    def test_send_dry_run_returns_true(self):
        n = DiscordNotifier(webhook_url=VALID_URL, dry_run=True)
        assert n.send(make_signal()) is True

    def test_send_dry_run_no_http(self):
        n = DiscordNotifier(webhook_url=VALID_URL, dry_run=True)
        with patch("core.notifier.requests.post") as mock_post:
            n.send(make_signal())
            mock_post.assert_not_called()

    def test_send_text_dry_run_returns_true(self):
        n = DiscordNotifier(webhook_url=VALID_URL, dry_run=True)
        assert n.send_text("heartbeat") is True

    def test_send_text_dry_run_no_http(self):
        n = DiscordNotifier(webhook_url=VALID_URL, dry_run=True)
        with patch("core.notifier.requests.post") as mock_post:
            n.send_text("heartbeat")
            mock_post.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
#  _build_payload()
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildPayload:

    def test_payload_has_embeds_key(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        payload = n._build_payload(make_signal("BUY"))
        assert "embeds" in payload
        assert len(payload["embeds"]) == 1

    def test_buy_signal_uses_green_color(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        payload = n._build_payload(make_signal("BUY"))
        assert payload["embeds"][0]["color"] == _BUY_COLOR

    def test_sell_signal_uses_red_color(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        payload = n._build_payload(make_signal("SELL", "tk_cross_down"))
        assert payload["embeds"][0]["color"] == _SELL_COLOR

    def test_embed_title_contains_direction(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        payload = n._build_payload(make_signal("BUY"))
        assert "BUY" in payload["embeds"][0]["title"]

    def test_embed_fields_contain_pair(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        payload = n._build_payload(make_signal("BUY"))
        field_names = [f["name"] for f in payload["embeds"][0]["fields"]]
        assert "Pair" in field_names

    def test_embed_fields_contain_price(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        payload = n._build_payload(make_signal("BUY"))
        field_names = [f["name"] for f in payload["embeds"][0]["fields"]]
        assert "Price" in field_names

    def test_detail_fields_included(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        payload = n._build_payload(make_signal("BUY"))
        field_names = [f["name"] for f in payload["embeds"][0]["fields"]]
        assert "Tenkan" in field_names
        assert "Kijun" in field_names
        assert "Cloud Top" in field_names

    def test_embed_has_footer(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        payload = n._build_payload(make_signal("BUY"))
        assert "footer" in payload["embeds"][0]

    def test_embed_has_timestamp(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        payload = n._build_payload(make_signal("BUY"))
        assert "timestamp" in payload["embeds"][0]


# ─────────────────────────────────────────────────────────────────────────────
#  _post_with_retry()
# ─────────────────────────────────────────────────────────────────────────────

class TestPostWithRetry:

    def test_returns_true_on_204(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        with patch("core.notifier.requests.post", return_value=mock_resp):
            assert n._post_with_retry({"content": "test"}) is True

    def test_returns_false_after_all_retries_fail(self):
        n = DiscordNotifier(webhook_url=VALID_URL, max_retries=2, retry_delay=0)
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        with patch("core.notifier.requests.post", return_value=mock_resp):
            with patch("core.notifier.time.sleep"):
                assert n._post_with_retry({"content": "test"}) is False

    def test_retries_correct_number_of_times(self):
        n = DiscordNotifier(webhook_url=VALID_URL, max_retries=3, retry_delay=0)
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "error"
        with patch("core.notifier.requests.post", return_value=mock_resp) as mock_post:
            with patch("core.notifier.time.sleep"):
                n._post_with_retry({"content": "test"})
                assert mock_post.call_count == 3

    def test_handles_request_exception(self):
        import requests as req
        n = DiscordNotifier(webhook_url=VALID_URL, max_retries=2, retry_delay=0)
        with patch("core.notifier.requests.post", side_effect=req.RequestException("timeout")):
            with patch("core.notifier.time.sleep"):
                assert n._post_with_retry({"content": "test"}) is False

    def test_handles_429_rate_limit(self):
        n = DiscordNotifier(webhook_url=VALID_URL, max_retries=2, retry_delay=0)
        rate_limit_resp = MagicMock()
        rate_limit_resp.status_code = 429
        rate_limit_resp.json.return_value = {"retry_after": 0.01}
        ok_resp = MagicMock()
        ok_resp.status_code = 204
        with patch("core.notifier.requests.post",
                   side_effect=[rate_limit_resp, ok_resp]):
            with patch("core.notifier.time.sleep"):
                assert n._post_with_retry({"content": "test"}) is True

    def test_send_calls_post_with_webhook_url(self):
        n = DiscordNotifier(webhook_url=VALID_URL)
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        with patch("core.notifier.requests.post", return_value=mock_resp) as mock_post:
            n.send(make_signal())
            assert mock_post.call_args[0][0] == VALID_URL
