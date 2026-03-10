"""
trade_bot.py
─────────────────────────────────────────────────────────────────────────────
Main orchestrator for the MT5 Ichimoku Trading Bot v3.

Usage:
    python trade_bot.py                     # uses config/strategy_config.json
    python trade_bot.py --config path.json  # custom config
    python trade_bot.py --sim               # force simulation mode
    python trade_bot.py --once              # run one cycle and exit
    python trade_bot.py --dashboard-url https://your-app.onrender.com --dashboard-secret mysecret
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from core.config_loader import ConfigLoader, Config
from core.candle_close_guard import CandleCloseGuard
from core.ichimoku_calculator import IchimokuCalculator, IchimokuValues, pip_size
from core.signal_engine import SignalEngine, Signal
from core.lot_calculator import LotCalculator, SymbolInfo as LotSymbolInfo
from core.sltp_builder import SLTPBuilder
from core.risk_manager import RiskGuard, PositionInfo as RiskPositionInfo
from core.mt5_connector import MT5Connector
from core.order_executor import OrderExecutor
from core.session_filter import SessionFilter
from core.trend_filter import TrendFilter
from core.news_filter import NewsFilter
from core.break_even_manager import BreakEvenManager
from core.position_manager import PositionManager
from core.action_verifier import ActionVerifier
from core.trade_event_listener import TradeEventListener
from utils.failed_action_logger import FailedActionLogger
from utils.trade_logger import TradeLogger
from utils.state import BotState, SignalSnapshot, PositionSnapshot, TradeRecord
from utils.logger import setup_logging
from utils.dashboard_server import DashboardServer
from utils.state_pusher import StatePusher


class TradeBotOrchestrator:
    """Main trading bot orchestrator."""

    def __init__(
        self,
        config: Config,
        force_sim: bool = False,
        dashboard_url: str = "",
        dashboard_secret: str = "",
    ) -> None:
        self.cfg = config
        self._running = False

        # Core components
        self.mt5 = MT5Connector(config, force_sim=force_sim)
        self.executor = OrderExecutor(config, self.mt5)
        self.guard = CandleCloseGuard()
        self.calculator = IchimokuCalculator(config.ichimoku)
        self.signal_engine = SignalEngine(config.ichimoku)
        self.lot_calc = LotCalculator(config.risk_management)
        self.sltp = SLTPBuilder(config.risk_management)
        self.risk_guard = RiskGuard(config)

        # Filters
        self.session_filter = SessionFilter(config.session_filter)
        self.trend_filter = TrendFilter(IchimokuCalculator(config.ichimoku))
        self.news_filter = NewsFilter(config.news_filter)

        # Position management
        self.be_manager = BreakEvenManager(config.risk_management.break_even, self.executor)
        self.pos_manager = PositionManager(
            config, self.executor, self.be_manager, self.signal_engine
        )

        # Verification
        self.failed_logger = FailedActionLogger(config.logging.log_dir)
        self.trade_logger = TradeLogger(config.logging.log_dir)
        self.verifier = ActionVerifier(config, self.mt5, self.failed_logger)
        self.event_listener = TradeEventListener(
            self.mt5, self.verifier, self.trade_logger
        )

        # State & Dashboard
        self.state = BotState()
        self.dashboard = DashboardServer(config.dashboard, self.state)
        self.state_pusher: Optional[StatePusher] = None
        if dashboard_url:
            self.state_pusher = StatePusher(
                self.state, dashboard_url, dashboard_secret
            )

    def start(self, run_once: bool = False) -> None:
        """Start the bot main loop."""
        if not self.mt5.connect():
            logger.error("Failed to connect to MT5. Exiting.")
            return

        # Setup
        setup_logging(self.cfg.logging, self.state)
        account = self.mt5.get_account_info()
        self.risk_guard.set_start_balance(account.balance)
        self.state.set_start_balance(account.balance)
        self.state.set_target_pct(self.cfg.goal.target_profit_pct)
        self.state.update_account(account.balance, account.equity)

        logger.info(f"Bot started | Balance: ${account.balance:.2f} | "
                    f"Mode: {'SIM' if self.mt5.is_simulation else 'LIVE'} | "
                    f"Pairs: {self.cfg.pairs}")

        # Start dashboard
        self.dashboard.start()
        if self.state_pusher:
            self.state_pusher.start()

        self._running = True
        cycle = 0

        while self._running:
            try:
                cycle += 1
                self._run_cycle(cycle)

                if run_once:
                    break

                interval = self.cfg.scheduler.bar_check_interval_sec
                time.sleep(interval)

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                break
            except Exception as e:
                logger.exception(f"Error in main loop: {e}")
                if run_once:
                    break
                time.sleep(10)

        self._shutdown()

    def _run_cycle(self, cycle: int) -> None:
        """Run one bot cycle: scan all pairs, manage positions, poll events."""
        now = datetime.now(timezone.utc)

        # Update account info
        account = self.mt5.get_account_info()
        self.state.update_account(account.balance, account.equity)

        # Check halt conditions
        if self.risk_guard.is_halted:
            self.state.set_halted(True, self.risk_guard.halt_reason)
            if cycle == 1:
                logger.warning(f"Bot halted: {self.risk_guard.halt_reason}")
            return

        signal_snapshots: list[SignalSnapshot] = []
        ichi_by_symbol: dict[str, IchimokuValues] = {}
        current_prices: dict[str, float] = {}

        for symbol in self.cfg.pairs:
            try:
                self._process_symbol(
                    symbol, now, account, signal_snapshots,
                    ichi_by_symbol, current_prices
                )
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")

        # Update state
        self.state.update_signals(signal_snapshots)

        # Position management
        positions = self.mt5.get_open_positions()
        closed_tickets = self.pos_manager.manage_positions(
            positions, ichi_by_symbol, current_prices
        )

        # Update position snapshots
        pos_snaps = [
            PositionSnapshot(
                ticket=p.ticket, symbol=p.symbol,
                direction="BUY" if p.type == 0 else "SELL",
                entry_price=p.price_open, current_sl=p.sl,
                unrealized_pnl=p.profit,
            )
            for p in self.mt5.get_open_positions()
        ]
        self.state.update_positions(pos_snaps)

        # Poll trade events
        closed_trades = self.event_listener.poll()
        for ct in closed_trades:
            self.state.add_trade(TradeRecord(
                order_id=ct.order_id, symbol=ct.symbol,
                direction=ct.action_type, pnl=ct.pnl,
                exit_reason=ct.exit_reason,
            ))
            self.risk_guard.record_trade_close(ct.pnl)

        # Update verification stats
        self.state.update_verification_stats(
            self.verifier.stats, self.verifier.failure_counts
        )

        if cycle % 10 == 0:
            logger.info(
                f"Cycle {cycle} | Balance: ${account.balance:.2f} | "
                f"Open: {len(positions)} | "
                f"Trades: {self.verifier.stats.get('total', 0)}"
            )

    def _process_symbol(
        self,
        symbol: str,
        now: datetime,
        account,
        signal_snapshots: list,
        ichi_by_symbol: dict,
        current_prices: dict,
    ) -> None:
        """Process one symbol: fetch, compute, evaluate, execute."""
        tf = self.cfg.timeframes.primary

        # Fetch bars
        df = self.mt5.get_bars(symbol, tf, 300)
        if len(df) < 80:
            return

        # Candle close guard
        df_closed, is_new = self.guard.get_closed_bars(df, symbol)
        if df_closed is None:
            return

        # Compute Ichimoku
        ichi = self.calculator.compute(df_closed, symbol)
        if ichi is None:
            return

        ichi_by_symbol[symbol] = ichi
        current_prices[symbol] = ichi.close

        # Build signal snapshot
        sig_snap = SignalSnapshot(
            symbol=symbol,
            signal="NEUTRAL",
            close=ichi.close,
            tenkan=ichi.tenkan,
            kijun=ichi.kijun,
            cloud_position="above" if ichi.close > ichi.cloud_top else
                          "below" if ichi.close < ichi.cloud_bottom else "inside",
            cloud_thickness=ichi.cloud_thickness_pips,
        )

        if not is_new:
            signal_snapshots.append(sig_snap)
            return

        # Evaluate signal
        result = self.signal_engine.evaluate(ichi, df_closed)
        sig_snap.signal = result.signal.value
        signal_snapshots.append(sig_snap)

        if result.signal == Signal.NEUTRAL:
            return

        direction = result.signal.value
        logger.info(f"Signal: {direction} {symbol} (mode={result.mode_used})")

        # Session filter
        ok, reason = self.session_filter.is_tradeable(now)
        if not ok:
            logger.info(f"Session filter blocked {symbol}: {reason}")
            return

        # News filter
        ok, reason = self.news_filter.is_clear(symbol, now)
        if not ok:
            logger.info(f"News filter blocked {symbol}: {reason}")
            return

        # D1 trend filter (optional)
        try:
            df_d1 = self.mt5.get_bars(symbol, "D1", 200)
            confirmed, reason = self.trend_filter.confirms_direction(
                df_d1, symbol, direction
            )
            if not confirmed:
                logger.info(f"D1 trend filter blocked {symbol}: {reason}")
                return
        except Exception:
            pass  # Proceed without D1 confirmation if bars unavailable

        # Risk guard
        positions = self.mt5.get_open_positions()
        risk_positions = [
            RiskPositionInfo(symbol=p.symbol, ticket=p.ticket, profit=p.profit)
            for p in positions
        ]
        can_trade, reason = self.risk_guard.can_trade(
            symbol, risk_positions, account.balance, account.equity
        )
        if not can_trade:
            logger.info(f"Risk guard blocked {symbol}: {reason}")
            return

        # Calculate SL/TP
        sltp = self.sltp.build(direction, ichi.close, symbol, ichi, df_closed)
        if sltp is None:
            logger.warning(f"SL/TP rejected for {symbol}")
            return

        # Calculate lot size
        sym_info = self.mt5.get_symbol_info(symbol)
        lot_info = LotSymbolInfo(
            volume_min=sym_info.volume_min,
            volume_max=sym_info.volume_max,
            volume_step=sym_info.volume_step,
            contract_size=sym_info.contract_size,
            name=symbol,
        )
        lot_size = self.lot_calc.calculate(
            account.balance, ichi.close, sltp.sl, symbol, lot_info
        )

        # Execute order
        order_result = self.executor.open_trade(
            symbol=symbol,
            direction=direction,
            volume=lot_size,
            sl=sltp.sl,
            tp=sltp.tp,
        )

        if order_result.success:
            logger.info(
                f"Trade executed: {direction} {lot_size} {symbol} @ {order_result.price} "
                f"SL={sltp.sl} TP={sltp.tp}"
            )
        else:
            logger.error(f"Trade failed: {symbol} — {order_result.comment}")

    def _shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down...")
        self._running = False
        if self.state_pusher:
            self.state_pusher.stop()
        self.mt5.disconnect()
        logger.info("Bot stopped.")

    def stop(self) -> None:
        """Signal the bot to stop."""
        self._running = False


def main() -> None:
    parser = argparse.ArgumentParser(description="MT5 Ichimoku Trading Bot v3")
    parser.add_argument("--config", default="config/strategy_config.json",
                        help="Path to strategy config JSON")
    parser.add_argument("--sim", action="store_true",
                        help="Force simulation mode")
    parser.add_argument("--once", action="store_true",
                        help="Run one cycle and exit")
    parser.add_argument("--dashboard-url", default="",
                        help="Remote dashboard URL to push state to")
    parser.add_argument("--dashboard-secret", default="",
                        help="Secret token for dashboard auth")
    args = parser.parse_args()

    config = ConfigLoader.load(args.config)

    bot = TradeBotOrchestrator(
        config,
        force_sim=args.sim,
        dashboard_url=args.dashboard_url,
        dashboard_secret=args.dashboard_secret,
    )

    # Graceful shutdown handlers
    def _signal_handler(sig, frame):
        logger.info(f"Signal {sig} received — stopping bot")
        bot.stop()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    bot.start(run_once=args.once)


if __name__ == "__main__":
    main()
