"""
dashboard/app.py
─────────────────────────────────────────────────────────────────────────────
Standalone deployable FastAPI dashboard for IchiBot v3.

Receives state updates via POST /api/state from the local trading bot.
Serves a live HTML dashboard via WebSocket at /.

Deploy on Render, Koyeb, Fly.io, or any platform that supports Python.

Usage (local):
    cd dashboard
    pip install -r requirements.txt
    uvicorn app:app --host 0.0.0.0 --port 8000

The trading bot pushes state every few seconds:
    POST /api/state  (JSON body = BotSnapshot)
    Header: Authorization: Bearer <DASHBOARD_SECRET>
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="IchiBot v3 Dashboard")

# ── State store ──────────────────────────────────────────────────────────────

DASHBOARD_SECRET = os.environ.get("DASHBOARD_SECRET", "")

_state: dict = {
    "balance": 0,
    "equity": 0,
    "goal_progress_pct": 0,
    "signals": [],
    "positions": [],
    "recent_trades": [],
    "verification_stats": {},
    "log_lines": [],
    "timestamp": "",
    "is_halted": False,
    "halt_reason": "",
}
_last_update: float = 0


# ── API endpoints ────────────────────────────────────────────────────────────

@app.post("/api/state")
async def update_state(request: Request):
    """Receive state update from the trading bot."""
    global _state, _last_update

    # Auth check
    if DASHBOARD_SECRET:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {DASHBOARD_SECRET}":
            raise HTTPException(status_code=401, detail="Unauthorized")

    body = await request.json()
    _state = body
    _last_update = time.time()
    return {"status": "ok"}


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    age = time.time() - _last_update if _last_update > 0 else -1
    return {
        "status": "ok",
        "last_update_sec_ago": round(age, 1) if age >= 0 else "never",
        "has_data": _last_update > 0,
    }


# ── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = dict(_state)
            if _last_update == 0:
                data["log_lines"] = ["Waiting for bot to connect and push state..."]
            await websocket.send_text(json.dumps(data, default=str))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# ── Dashboard HTML ───────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html>
<head>
<title>IchiBot v3 Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', system-ui, monospace; background: #0a0e1a; color: #c8d6e5; padding: 16px; }
  h1 { color: #00d4ff; margin-bottom: 6px; font-size: 22px; }
  .subtitle { color: #576574; font-size: 12px; margin-bottom: 16px; }
  h2 { color: #00d4ff; margin: 12px 0 6px; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
  .panel { background: #141b2d; border: 1px solid #1e2a4a; border-radius: 10px; padding: 14px; }
  .full { grid-column: 1 / -1; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 5px 8px; text-align: left; border-bottom: 1px solid #1e2a4a; }
  th { color: #00d4ff; font-weight: 600; font-size: 11px; text-transform: uppercase; }
  .buy { color: #00ff88; font-weight: 600; }
  .sell { color: #ff6b6b; font-weight: 600; }
  .correct { color: #00ff88; }
  .incorrect { color: #ff6b6b; }
  .neutral { color: #576574; }
  .progress-bar { background: #1e2a4a; border-radius: 6px; height: 22px; margin: 6px 0; overflow: hidden; }
  .progress-fill { background: linear-gradient(90deg, #00d4ff, #00ff88); height: 100%; border-radius: 6px; transition: width 0.5s; }
  .halted { background: #ff6b6b; color: white; padding: 10px; border-radius: 8px; text-align: center; font-weight: 600; margin-bottom: 12px; }
  #log { font-size: 11px; max-height: 250px; overflow-y: auto; white-space: pre-wrap; color: #8395a7; line-height: 1.6; }
  .stat-big { font-size: 28px; font-weight: 700; color: #fff; }
  .stat-label { font-size: 11px; color: #576574; text-transform: uppercase; }
  .stat-row { display: flex; gap: 20px; margin: 8px 0; }
  .stat-item { flex: 1; }
  .conn-status { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
  .conn-ok { background: #00ff88; }
  .conn-off { background: #ff6b6b; }
  .badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; }
  .badge-correct { background: #00ff8822; color: #00ff88; }
  .badge-incorrect { background: #ff6b6b22; color: #ff6b6b; }
</style>
</head>
<body>
<h1>IchiBot v3 <span id="conn"><span class="conn-status conn-off"></span></span></h1>
<div class="subtitle">Ichimoku Kinko Hyo Trading Dashboard &mdash; <span id="ts">connecting...</span></div>
<div id="halt-banner" style="display:none" class="halted"></div>
<div class="grid">

  <div class="panel">
    <h2>Account</h2>
    <div class="stat-row">
      <div class="stat-item">
        <div class="stat-label">Balance</div>
        <div class="stat-big" id="balance">$0.00</div>
      </div>
      <div class="stat-item">
        <div class="stat-label">Equity</div>
        <div class="stat-big" id="equity" style="font-size:20px;color:#8395a7">$0.00</div>
      </div>
    </div>
    <div class="stat-label">Goal Progress</div>
    <div class="progress-bar"><div class="progress-fill" id="goal-bar" style="width:0%"></div></div>
    <div style="text-align:right;font-size:12px;color:#00d4ff" id="goal-pct">0%</div>
  </div>

  <div class="panel">
    <h2>Verification Stats</h2>
    <div class="stat-row">
      <div class="stat-item">
        <div class="stat-label">Total Trades</div>
        <div class="stat-big" id="v-total">0</div>
      </div>
      <div class="stat-item">
        <div class="stat-label">Correct</div>
        <div class="stat-big correct" id="v-correct">0</div>
      </div>
      <div class="stat-item">
        <div class="stat-label">Incorrect</div>
        <div class="stat-big incorrect" id="v-incorrect">0</div>
      </div>
    </div>
    <div id="v-failures" class="stat-label" style="margin-top:8px"></div>
  </div>

  <div class="panel full">
    <h2>Signals &mdash; 8 Pairs</h2>
    <table><thead><tr><th>Symbol</th><th>Signal</th><th>Close</th><th>Tenkan</th><th>Kijun</th><th>Cloud</th><th>Thickness</th></tr></thead>
    <tbody id="signals-body"><tr><td colspan="7" class="neutral">Waiting for data...</td></tr></tbody></table>
  </div>

  <div class="panel full">
    <h2>Open Positions</h2>
    <table><thead><tr><th>Ticket</th><th>Symbol</th><th>Dir</th><th>Entry</th><th>SL</th><th>PnL</th><th>Trailing</th></tr></thead>
    <tbody id="positions-body"><tr><td colspan="7" class="neutral">No positions</td></tr></tbody></table>
  </div>

  <div class="panel full">
    <h2>Recent Trades (Last 20)</h2>
    <table><thead><tr><th>Order</th><th>Symbol</th><th>Dir</th><th>PnL</th><th>Exit</th><th>Verification</th></tr></thead>
    <tbody id="trades-body"><tr><td colspan="6" class="neutral">No trades yet</td></tr></tbody></table>
  </div>

  <div class="panel full">
    <h2>System Log</h2>
    <div id="log">Waiting for bot connection...</div>
  </div>

</div>
<script>
let ws;
function connect() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.onopen = () => {
    document.getElementById('conn').innerHTML = '<span class="conn-status conn-ok"></span>';
  };
  ws.onclose = () => {
    document.getElementById('conn').innerHTML = '<span class="conn-status conn-off"></span>';
    setTimeout(connect, 3000);
  };
  ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    document.getElementById('balance').textContent = '$' + d.balance.toFixed(2);
    document.getElementById('equity').textContent = '$' + d.equity.toFixed(2);
    document.getElementById('goal-bar').style.width = Math.min(d.goal_progress_pct, 100) + '%';
    document.getElementById('goal-pct').textContent = d.goal_progress_pct.toFixed(1) + '%';
    document.getElementById('ts').textContent = d.timestamp ? new Date(d.timestamp).toLocaleTimeString() : 'no data';

    const vs = d.verification_stats || {};
    document.getElementById('v-total').textContent = vs.total || 0;
    document.getElementById('v-correct').textContent = vs.correct || 0;
    document.getElementById('v-incorrect').textContent = vs.incorrect || 0;

    let failText = '';
    for (const [k,v] of Object.entries(vs)) {
      if (k.startsWith('fail_')) failText += k.replace('fail_','') + ': ' + v + '  ';
    }
    document.getElementById('v-failures').textContent = failText || 'No failures';

    // Signals
    let sh = '';
    for (const s of d.signals || []) {
      const cls = s.signal === 'BUY' ? 'buy' : s.signal === 'SELL' ? 'sell' : 'neutral';
      sh += `<tr><td>${s.symbol}</td><td class="${cls}">${s.signal}</td><td>${s.close.toFixed(5)}</td><td>${s.tenkan.toFixed(5)}</td><td>${s.kijun.toFixed(5)}</td><td>${s.cloud_position}</td><td>${s.cloud_thickness.toFixed(1)}</td></tr>`;
    }
    document.getElementById('signals-body').innerHTML = sh || '<tr><td colspan="7" class="neutral">No signals</td></tr>';

    // Positions
    let ph = '';
    for (const p of d.positions || []) {
      const cls = p.direction === 'BUY' ? 'buy' : 'sell';
      ph += `<tr><td>${p.ticket}</td><td>${p.symbol}</td><td class="${cls}">${p.direction}</td><td>${p.entry_price.toFixed(5)}</td><td>${p.current_sl.toFixed(5)}</td><td class="${p.unrealized_pnl>=0?'correct':'incorrect'}">$${p.unrealized_pnl.toFixed(2)}</td><td>${p.trailing_status}</td></tr>`;
    }
    document.getElementById('positions-body').innerHTML = ph || '<tr><td colspan="7" class="neutral">No positions</td></tr>';

    // Trades
    let th = '';
    for (const t of (d.recent_trades || []).slice().reverse()) {
      const vcls = (t.verification||'').startsWith('CORRECT') ? 'badge-correct' : 'badge-incorrect';
      th += `<tr><td>${t.order_id}</td><td>${t.symbol}</td><td class="${t.direction==='BUY'?'buy':'sell'}">${t.direction}</td><td class="${t.pnl>=0?'correct':'incorrect'}">$${t.pnl.toFixed(2)}</td><td>${t.exit_reason||''}</td><td><span class="badge ${vcls}">${t.verification||'—'}</span></td></tr>`;
    }
    document.getElementById('trades-body').innerHTML = th || '<tr><td colspan="6" class="neutral">No trades yet</td></tr>';

    // Log
    const logLines = d.log_lines || [];
    document.getElementById('log').textContent = logLines.join('\\n') || 'No log entries';

    // Halt banner
    const banner = document.getElementById('halt-banner');
    if (d.is_halted) { banner.style.display = 'block'; banner.textContent = 'BOT HALTED: ' + d.halt_reason; }
    else { banner.style.display = 'none'; }
  };
}
connect();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return DASHBOARD_HTML
