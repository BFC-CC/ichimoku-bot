"""
utils/dashboard_server.py
─────────────────────────────────────────────────────────────────────────────
FastAPI + WebSocket dashboard at localhost:8000.

Displays: account panel, signals table, open positions, trade log,
verification stats, and live log stream.
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import asdict
from typing import Optional

from loguru import logger

from core.config_loader import DashboardConfig
from utils.state import BotState

# Lazy imports for optional dependencies
_fastapi_available = False
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    import uvicorn
    _fastapi_available = True
except ImportError:
    pass


DASHBOARD_HTML = """<!DOCTYPE html>
<html>
<head>
<title>IchiBot v3 Dashboard</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: monospace; background: #1a1a2e; color: #e0e0e0; padding: 20px; }
  h1 { color: #00d4ff; margin-bottom: 20px; }
  h2 { color: #00d4ff; margin: 15px 0 8px; font-size: 14px; text-transform: uppercase; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
  .panel { background: #16213e; border: 1px solid #0f3460; border-radius: 8px; padding: 15px; }
  .full { grid-column: 1 / -1; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #0f3460; }
  th { color: #00d4ff; }
  .buy { color: #00ff88; }
  .sell { color: #ff4444; }
  .correct { color: #00ff88; }
  .incorrect { color: #ff4444; }
  .neutral { color: #888; }
  .progress-bar { background: #0f3460; border-radius: 4px; height: 20px; margin: 5px 0; }
  .progress-fill { background: #00d4ff; height: 100%; border-radius: 4px; transition: width 0.5s; }
  .halted { background: #ff4444; color: white; padding: 10px; border-radius: 4px; text-align: center; }
  #log { font-size: 11px; max-height: 300px; overflow-y: auto; white-space: pre-wrap; }
  .stat { font-size: 24px; font-weight: bold; }
  .label { font-size: 12px; color: #888; }
</style>
</head>
<body>
<h1>IchiBot v3 — Live Dashboard</h1>
<div id="halt-banner" style="display:none" class="halted"></div>
<div class="grid">

  <div class="panel">
    <h2>Account</h2>
    <div><span class="label">Balance:</span> <span id="balance" class="stat">$0</span></div>
    <div><span class="label">Equity:</span> <span id="equity">$0</span></div>
    <div><span class="label">Goal Progress:</span></div>
    <div class="progress-bar"><div class="progress-fill" id="goal-bar" style="width:0%"></div></div>
    <div id="goal-pct" class="label">0%</div>
  </div>

  <div class="panel">
    <h2>Verification Stats</h2>
    <div><span class="label">Total:</span> <span id="v-total" class="stat">0</span></div>
    <div><span class="label">Correct:</span> <span id="v-correct" class="correct">0</span>
         <span class="label">Incorrect:</span> <span id="v-incorrect" class="incorrect">0</span></div>
    <div id="v-failures" class="label"></div>
  </div>

  <div class="panel full">
    <h2>Signals (8 Pairs)</h2>
    <table><thead><tr><th>Symbol</th><th>Signal</th><th>Close</th><th>Tenkan</th><th>Kijun</th><th>Cloud</th><th>Thickness</th></tr></thead>
    <tbody id="signals-body"></tbody></table>
  </div>

  <div class="panel full">
    <h2>Open Positions</h2>
    <table><thead><tr><th>Ticket</th><th>Symbol</th><th>Dir</th><th>Entry</th><th>SL</th><th>PnL</th><th>Trailing</th></tr></thead>
    <tbody id="positions-body"></tbody></table>
  </div>

  <div class="panel full">
    <h2>Recent Trades (Last 20)</h2>
    <table><thead><tr><th>Order</th><th>Symbol</th><th>Dir</th><th>PnL</th><th>Exit</th><th>Verification</th></tr></thead>
    <tbody id="trades-body"></tbody></table>
  </div>

  <div class="panel full">
    <h2>System Log</h2>
    <div id="log"></div>
  </div>

</div>
<script>
const ws = new WebSocket(`ws://${location.host}/ws`);
ws.onmessage = (e) => {
  const d = JSON.parse(e.data);
  document.getElementById('balance').textContent = '$' + d.balance.toFixed(2);
  document.getElementById('equity').textContent = '$' + d.equity.toFixed(2);
  document.getElementById('goal-bar').style.width = d.goal_progress_pct + '%';
  document.getElementById('goal-pct').textContent = d.goal_progress_pct + '%';

  const vs = d.verification_stats || {};
  document.getElementById('v-total').textContent = vs.total || 0;
  document.getElementById('v-correct').textContent = vs.correct || 0;
  document.getElementById('v-incorrect').textContent = vs.incorrect || 0;

  let failText = '';
  for (const [k,v] of Object.entries(vs)) {
    if (k.startsWith('fail_')) failText += k.replace('fail_','') + ': ' + v + '  ';
  }
  document.getElementById('v-failures').textContent = failText;

  // Signals
  let sh = '';
  for (const s of d.signals || []) {
    const cls = s.signal === 'BUY' ? 'buy' : s.signal === 'SELL' ? 'sell' : 'neutral';
    sh += `<tr><td>${s.symbol}</td><td class="${cls}">${s.signal}</td><td>${s.close.toFixed(5)}</td><td>${s.tenkan.toFixed(5)}</td><td>${s.kijun.toFixed(5)}</td><td>${s.cloud_position}</td><td>${s.cloud_thickness.toFixed(1)}</td></tr>`;
  }
  document.getElementById('signals-body').innerHTML = sh;

  // Positions
  let ph = '';
  for (const p of d.positions || []) {
    const cls = p.direction === 'BUY' ? 'buy' : 'sell';
    ph += `<tr><td>${p.ticket}</td><td>${p.symbol}</td><td class="${cls}">${p.direction}</td><td>${p.entry_price.toFixed(5)}</td><td>${p.current_sl.toFixed(5)}</td><td>${p.unrealized_pnl.toFixed(2)}</td><td>${p.trailing_status}</td></tr>`;
  }
  document.getElementById('positions-body').innerHTML = ph;

  // Trades
  let th = '';
  for (const t of (d.recent_trades || []).reverse()) {
    const cls = t.pnl >= 0 ? 'correct' : 'incorrect';
    const vcls = t.verification.startsWith('CORRECT') ? 'correct' : 'incorrect';
    th += `<tr><td>${t.order_id}</td><td>${t.symbol}</td><td>${t.direction}</td><td class="${cls}">$${t.pnl.toFixed(2)}</td><td>${t.exit_reason}</td><td class="${vcls}">${t.verification}</td></tr>`;
  }
  document.getElementById('trades-body').innerHTML = th;

  // Log
  document.getElementById('log').textContent = (d.log_lines || []).join('\\n');

  // Halt banner
  const banner = document.getElementById('halt-banner');
  if (d.is_halted) { banner.style.display = 'block'; banner.textContent = 'BOT HALTED: ' + d.halt_reason; }
  else { banner.style.display = 'none'; }
};
</script>
</body>
</html>"""


class DashboardServer:
    """FastAPI dashboard with WebSocket data push."""

    def __init__(self, config: DashboardConfig, state: BotState) -> None:
        self.cfg = config
        self.state = state
        self._thread: Optional[threading.Thread] = None

        if not _fastapi_available:
            logger.warning("FastAPI/uvicorn not installed — dashboard disabled")
            return

        self.app = FastAPI(title="IchiBot v3")

        @self.app.get("/", response_class=HTMLResponse)
        async def index():
            return DASHBOARD_HTML

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            try:
                while True:
                    snap = self.state.snapshot()
                    data = asdict(snap)
                    await websocket.send_text(json.dumps(data, default=str))
                    await asyncio.sleep(2)
            except WebSocketDisconnect:
                pass
            except Exception:
                pass

    def start(self) -> None:
        """Start the dashboard server in a background thread."""
        if not _fastapi_available:
            return
        if not self.cfg.enabled:
            return

        def _run():
            uvicorn.run(
                self.app,
                host=self.cfg.host,
                port=self.cfg.port,
                log_level="warning",
            )

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        logger.info(f"Dashboard started at http://{self.cfg.host}:{self.cfg.port}")
