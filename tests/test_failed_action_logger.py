"""Tests for utils/failed_action_logger.py"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest

from utils.failed_action_logger import FailedActionLogger, FailedActionRecord, COLUMNS


class TestFailedActionLogger:
    def test_creates_file_with_header(self, tmp_path):
        logger = FailedActionLogger(str(tmp_path))
        record = FailedActionRecord(
            timestamp_utc="2024-06-01 12:00:00",
            order_id=1001,
            symbol="EURUSD",
            failure_type="SL_HIT",
            pnl_usd=-50.0,
        )
        logger.append(record)
        assert logger.file_path.exists()

        with open(logger.file_path) as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == COLUMNS
            row = next(reader)
            assert len(row) == len(COLUMNS)

    def test_appends_without_overwrite(self, tmp_path):
        logger = FailedActionLogger(str(tmp_path))
        for i in range(3):
            logger.append(FailedActionRecord(
                order_id=i, symbol="EURUSD", failure_type="SL_HIT"
            ))

        with open(logger.file_path) as f:
            rows = list(csv.reader(f))
        assert len(rows) == 4  # 1 header + 3 data rows

    def test_correct_columns_count(self, tmp_path):
        assert len(COLUMNS) == 29

    def test_float_formatting(self, tmp_path):
        logger = FailedActionLogger(str(tmp_path))
        logger.append(FailedActionRecord(
            entry_price=1.12345, pnl_usd=-50.123, symbol="EURUSD"
        ))
        with open(logger.file_path) as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert row["entry_price"] == "1.12345"
        assert row["pnl_usd"] == "-50.12"

    def test_conditions_met_serialization(self, tmp_path):
        logger = FailedActionLogger(str(tmp_path))
        logger.append(FailedActionRecord(
            conditions_met="price_above_cloud=True|tk_above_kijun=False",
            symbol="EURUSD",
        ))
        with open(logger.file_path) as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert "price_above_cloud=True" in row["conditions_met"]
