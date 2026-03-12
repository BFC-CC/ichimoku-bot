"""
core/news_calendar.py
---------------------------------------------------------------------
Calendar data layer for high-impact news events.
Supports static JSON events (recurring monthly + specific dates).
"""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from loguru import logger

from core.config_loader import NewsFilterConfig


@dataclass
class NewsEvent:
    name: str
    currency: str
    event_time: datetime  # UTC
    impact: str


class NewsCalendar:
    """Load and query news events from a static JSON file."""

    def __init__(self, config: NewsFilterConfig) -> None:
        self.cfg = config
        self._events: List[NewsEvent] = []
        if config.calendar_source == "static":
            self._events = self.load_static()

    def load_static(self) -> List[NewsEvent]:
        """Load events from the static JSON file."""
        path = Path(self.cfg.static_events_path)
        if not path.exists():
            logger.warning(f"News events file not found: {path}")
            return []

        try:
            with open(path, "r") as f:
                raw = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load news events: {e}")
            return []

        events: List[NewsEvent] = []

        # Specific dates
        for item in raw.get("specific_dates", []):
            try:
                dt = datetime.strptime(
                    f"{item['date']} {item['time_utc']}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=timezone.utc)
                events.append(NewsEvent(
                    name=item["name"],
                    currency=item["currency"],
                    event_time=dt,
                    impact=item.get("impact", "high"),
                ))
            except (KeyError, ValueError) as e:
                logger.warning(f"Skipping malformed specific event: {e}")

        # Recurring monthly: resolve for current year +/- 1 month
        now = datetime.now(timezone.utc)
        for month_offset in range(-1, 3):
            year = now.year
            month = now.month + month_offset
            if month < 1:
                month += 12
                year -= 1
            elif month > 12:
                month -= 12
                year += 1

            for item in raw.get("recurring_monthly", []):
                resolved = self._resolve_recurring(item, year, month)
                events.extend(resolved)

        logger.info(f"Loaded {len(events)} news events")
        return events

    def is_blackout(self, symbol: str, now_utc: datetime) -> tuple[bool, str]:
        """
        Check if the current time falls within a blackout window
        for any event affecting this symbol.

        Returns (is_blocked, reason).
        """
        before = timedelta(minutes=self.cfg.minutes_before)
        after = timedelta(minutes=self.cfg.minutes_after)

        for event in self._events:
            if event.impact not in self.cfg.impact_levels:
                continue
            if not self._currency_affects_symbol(event.currency, symbol):
                continue
            window_start = event.event_time - before
            window_end = event.event_time + after
            if window_start <= now_utc <= window_end:
                return True, f"{event.name} ({event.currency}) at {event.event_time.strftime('%H:%M UTC')}"

        return False, ""

    def _resolve_recurring(self, event_def: dict, year: int, month: int) -> List[NewsEvent]:
        """Resolve a recurring monthly event to concrete dates."""
        rule = event_def.get("rule", "")
        time_str = event_def.get("time_utc", "12:00")
        hour, minute = map(int, time_str.split(":"))
        events: List[NewsEvent] = []

        try:
            if rule == "first_friday":
                day = self._nth_weekday(year, month, calendar.FRIDAY, 1)
                if day:
                    events.append(self._make_event(event_def, year, month, day, hour, minute))
            elif rule == "first_tuesday":
                day = self._nth_weekday(year, month, calendar.TUESDAY, 1)
                if day:
                    events.append(self._make_event(event_def, year, month, day, hour, minute))
            elif rule == "mid_month":
                day_range = event_def.get("day_range", [10, 15])
                mid_day = (day_range[0] + day_range[1]) // 2
                max_day = calendar.monthrange(year, month)[1]
                mid_day = min(mid_day, max_day)
                events.append(self._make_event(event_def, year, month, mid_day, hour, minute))
        except (ValueError, IndexError):
            pass

        return events

    @staticmethod
    def _nth_weekday(year: int, month: int, weekday: int, n: int) -> int | None:
        """Find the nth occurrence of weekday in the given month."""
        cal = calendar.Calendar()
        count = 0
        for day, wd in cal.itermonthdays2(year, month):
            if day == 0:
                continue
            if wd == weekday:
                count += 1
                if count == n:
                    return day
        return None

    @staticmethod
    def _make_event(
        event_def: dict, year: int, month: int, day: int, hour: int, minute: int
    ) -> NewsEvent:
        dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        return NewsEvent(
            name=event_def["name"],
            currency=event_def["currency"],
            event_time=dt,
            impact=event_def.get("impact", "high"),
        )

    @staticmethod
    def _currency_affects_symbol(currency: str, symbol: str) -> bool:
        """Check if a currency is part of the forex pair symbol."""
        return currency.upper() in symbol.upper()
