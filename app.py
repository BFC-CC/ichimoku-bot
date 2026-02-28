"""
app.py
────────────────────────────────────────────────────────────────────────────
Streamlit web dashboard for the Ichimoku Forex Signal Bot.

Run with:
    streamlit run app.py
Opens at: http://localhost:8501
"""

from __future__ import annotations

import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from backtest.engine import BacktestConfig, BacktestEngine
from core.indicator import IchimokuConfig, IchimokuIndicator
from core.signal_detector import DetectorConfig, SignalDetector
from gui.chart import build_ichimoku_chart
from gui.demo_data import make_synthetic_candles

# ─────────────────────────────────────────────────────────────────────────────
#  Page config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Ichimoku Bot Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

CONFIG_PATH = ROOT / "config.yaml"


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def get_pairs(cfg: dict) -> list[str]:
    return [p["symbol"] for p in cfg.get("pairs", [])]


def get_timeframes(cfg: dict, symbol: str) -> list[str]:
    for p in cfg.get("pairs", []):
        if p["symbol"] == symbol:
            return p.get("timeframes", ["H1"])
    return ["H1"]


def fmt(val: float, decimals: int = 5) -> str:
    if isinstance(val, float) and math.isnan(val):
        return "—"
    return f"{val:.{decimals}f}"


# ─────────────────────────────────────────────────────────────────────────────
#  Sidebar navigation
# ─────────────────────────────────────────────────────────────────────────────

st.sidebar.title("Ichimoku Bot")
st.sidebar.caption("Forex Signal Dashboard")
st.sidebar.divider()

page = st.sidebar.radio(
    "Navigate to",
    ["Live", "Overview", "Indicator Chart", "Backtest", "Signal Log", "Configuration"],
    label_visibility="collapsed",
)

cfg = load_config()

# ─────────────────────────────────────────────────────────────────────────────
#  Page: Live
# ─────────────────────────────────────────────────────────────────────────────

if page == "Live":
    import time
    from gui.live_feed import fetch_live_candles, get_data_source

    st.title("Live Dashboard")
    source = get_data_source()
    if "MetaTrader5" in source:
        st.success(f"Connected · {source}")
    else:
        st.warning(f"Data source: {source} · Install mt5linux for real-time MT5 data")

    # ── Controls ──────────────────────────────────────────────────────────────
    all_pairs = get_pairs(cfg)
    ctrl1, ctrl2, ctrl3 = st.columns([2, 2, 2])
    with ctrl1:
        symbol = st.selectbox("Symbol", all_pairs, key="live_sym")
    with ctrl2:
        tf = st.selectbox("Timeframe", get_timeframes(cfg, symbol), key="live_tf")
    with ctrl3:
        refresh_sec = st.selectbox(
            "Auto-refresh",
            [30, 60, 120, 300],
            index=1,
            format_func=lambda x: f"{x} s",
            key="live_refresh_interval",
        )

    # Track refresh count in session state
    if "live_tick" not in st.session_state:
        st.session_state["live_tick"] = 0
    st.session_state["live_tick"] += 1
    tick = st.session_state["live_tick"]

    # ── Fetch live data ───────────────────────────────────────────────────────
    with st.spinner("Fetching live prices…"):
        try:
            candles = fetch_live_candles(symbol, tf, count=300)
            fetch_ok = True
        except Exception as exc:
            st.error(f"Data fetch failed: {exc}")
            fetch_ok = False

    if fetch_ok:
        now_utc = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        st.caption(
            f"Last updated: **{now_utc}** · "
            f"{len(candles)} candles · "
            f"refresh #{tick}"
        )

        # ── Ichimoku calculation ──────────────────────────────────────────────
        ic = cfg.get("ichimoku", {})
        indicator = IchimokuIndicator(IchimokuConfig(
            tenkan_period   = ic.get("tenkan_period",   9),
            kijun_period    = ic.get("kijun_period",   26),
            senkou_b_period = ic.get("senkou_b_period", 52),
            displacement    = ic.get("displacement",   26),
            chikou_shift    = ic.get("chikou_shift",   26),
        ))
        ichi_df = indicator.calculate(candles)
        latest  = indicator.latest_values(candles)

        # ── Live chart ────────────────────────────────────────────────────────
        st.plotly_chart(build_ichimoku_chart(candles, ichi_df), width="stretch")

        # ── Latest indicator values ───────────────────────────────────────────
        st.subheader("Current Indicator Values")
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Close",    fmt(latest["close"]))
        m2.metric("Tenkan",   fmt(latest["tenkan"]))
        m3.metric("Kijun",    fmt(latest["kijun"]))
        m4.metric("Senkou A", fmt(latest["senkou_a"]))
        m5.metric("Senkou B", fmt(latest["senkou_b"]))
        m6.metric("Chikou",   fmt(latest["chikou"]))

        # ── Signal detection on latest candle ─────────────────────────────────
        sg = cfg.get("signals", {})
        detector = SignalDetector(
            config=DetectorConfig(
                cooldown_minutes=0,   # show every detected crossover
                cloud_filter=sg.get("cloud_filter", True),
            ),
            enabled_signals={
                s for p in cfg.get("pairs", [])
                if p["symbol"] == symbol
                for s in p.get("enabled_signals", [])
            } or None,
        )

        last_ts = candles.index[-1]
        fired = detector.check(
            pair=symbol,
            timeframe=tf,
            indicators=latest,
            candle_time=last_ts,
        )

        if fired:
            for sig in fired:
                if sig.direction == "BUY":
                    st.success(
                        f"BUY signal · **{sig.signal_type.upper()}** · "
                        f"price {sig.price:.5f} · {last_ts.strftime('%H:%M UTC')}"
                    )
                else:
                    st.error(
                        f"SELL signal · **{sig.signal_type.upper()}** · "
                        f"price {sig.price:.5f} · {last_ts.strftime('%H:%M UTC')}"
                    )

            # Accumulate in session state
            if "live_signals" not in st.session_state:
                st.session_state["live_signals"] = []
            for sig in fired:
                entry = {
                    "Time":        last_ts.strftime("%Y-%m-%d %H:%M UTC"),
                    "Symbol":      sig.pair,
                    "TF":          sig.timeframe,
                    "Direction":   sig.direction,
                    "Signal Type": sig.signal_type,
                    "Price":       round(sig.price, 5),
                }
                # Deduplicate by (time + type)
                key = (entry["Time"], entry["Signal Type"])
                if not any(
                    (r["Time"], r["Signal Type"]) == key
                    for r in st.session_state["live_signals"]
                ):
                    st.session_state["live_signals"].insert(0, entry)

        # ── Session signal log ────────────────────────────────────────────────
        if st.session_state.get("live_signals"):
            st.subheader("Signals this session")
            st.dataframe(
                pd.DataFrame(st.session_state["live_signals"]),
                width="stretch",
                hide_index=True,
            )
            if st.button("Clear signal log"):
                st.session_state["live_signals"] = []
                st.rerun()

    # ── Countdown then auto-rerun ─────────────────────────────────────────────
    status = st.empty()
    for remaining in range(refresh_sec, 0, -1):
        status.caption(f"Next refresh in {remaining}s…")
        time.sleep(1)
    status.empty()
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
#  Page: Overview
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Overview":
    st.title("Overview")

    pairs_cfg = cfg.get("pairs", [])
    total_pairs = len(pairs_cfg)
    total_tfs   = sum(len(p.get("timeframes", [])) for p in pairs_cfg)
    all_sigs    = {s for p in pairs_cfg for s in p.get("enabled_signals", [])}
    dry_run     = cfg.get("general", {}).get("dry_run", True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pairs Configured",      total_pairs)
    c2.metric("Timeframe Slots",        total_tfs)
    c3.metric("Signal Types Active",    len(all_sigs))
    c4.metric("Dry Run",               "Yes" if dry_run else "No")

    st.divider()
    st.subheader("Pairs & Signals")
    rows = [
        {
            "Symbol":          p["symbol"],
            "Timeframes":      ", ".join(p.get("timeframes", [])),
            "Enabled Signals": ", ".join(p.get("enabled_signals", [])),
        }
        for p in pairs_cfg
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.divider()
    st.subheader("Ichimoku Parameters")
    ic = cfg.get("ichimoku", {})
    i1, i2, i3, i4, i5 = st.columns(5)
    i1.metric("Tenkan Period",   ic.get("tenkan_period",   9))
    i2.metric("Kijun Period",    ic.get("kijun_period",   26))
    i3.metric("Senkou B Period", ic.get("senkou_b_period", 52))
    i4.metric("Displacement",    ic.get("displacement",   26))
    i5.metric("Chikou Shift",    ic.get("chikou_shift",   26))

    st.divider()
    st.subheader("Signal Settings")
    sg = cfg.get("signals", {})
    s1, s2, s3 = st.columns(3)
    s1.metric("Cooldown (min)",     sg.get("cooldown_minutes", 30))
    s2.metric("Cloud Filter",       "On"  if sg.get("cloud_filter", True)       else "Off")
    s3.metric("Strong Signal Only", "Yes" if sg.get("strong_signal_only", False) else "No")

# ─────────────────────────────────────────────────────────────────────────────
#  Page: Indicator Chart
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Indicator Chart":
    st.title("Indicator Chart")
    st.caption("Synthetic candle data — demo mode (MT5 not available on Linux)")

    all_pairs = get_pairs(cfg)
    col1, col2, col3 = st.columns([2, 2, 3])
    with col1:
        symbol = st.selectbox("Symbol", all_pairs)
    with col2:
        tf = st.selectbox("Timeframe", get_timeframes(cfg, symbol))
    with col3:
        n_candles = st.slider("Candle Count", 100, 1000, 300, 50)

    candles = make_synthetic_candles(n_candles, symbol, tf)

    ic = cfg.get("ichimoku", {})
    indicator = IchimokuIndicator(IchimokuConfig(
        tenkan_period   = ic.get("tenkan_period",   9),
        kijun_period    = ic.get("kijun_period",   26),
        senkou_b_period = ic.get("senkou_b_period", 52),
        displacement    = ic.get("displacement",   26),
        chikou_shift    = ic.get("chikou_shift",   26),
    ))
    ichi_df = indicator.calculate(candles)
    latest  = indicator.latest_values(candles)

    st.plotly_chart(build_ichimoku_chart(candles, ichi_df), width="stretch")

    st.subheader("Latest Indicator Values")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Tenkan",   fmt(latest["tenkan"]))
    m2.metric("Kijun",    fmt(latest["kijun"]))
    m3.metric("Senkou A", fmt(latest["senkou_a"]))
    m4.metric("Senkou B", fmt(latest["senkou_b"]))
    m5.metric("Chikou",   fmt(latest["chikou"]))
    m6.metric("Close",    fmt(latest["close"]))

# ─────────────────────────────────────────────────────────────────────────────
#  Page: Backtest
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Backtest":
    st.title("Backtest")
    st.caption("Runs on synthetic candle data")

    all_pairs = get_pairs(cfg)
    col1, col2 = st.columns(2)
    with col1:
        bt_symbol = st.selectbox("Symbol", all_pairs)
        bt_tf     = st.selectbox("Timeframe", get_timeframes(cfg, bt_symbol))
    with col2:
        bt_from = st.date_input("From Date", value=date(2024, 1, 1))
        bt_to   = st.date_input("To Date",   value=date(2024, 12, 31))

    all_sig_types = sorted(SignalDetector.ALL_SIGNALS)
    selected_sigs = st.multiselect("Signal Types", all_sig_types, default=all_sig_types)
    cloud_on      = st.checkbox("Cloud Filter", value=cfg.get("signals", {}).get("cloud_filter", True))
    n_bt          = st.slider("Candle Count", 500, 5000, 2000, 500)

    if st.button("Run Backtest", type="primary"):
        with st.spinner("Running backtest on synthetic data..."):
            candles_bt = make_synthetic_candles(n_bt, bt_symbol, bt_tf)
            ic = cfg.get("ichimoku", {})
            bt_config = BacktestConfig(
                ichimoku=IchimokuConfig(
                    tenkan_period   = ic.get("tenkan_period",   9),
                    kijun_period    = ic.get("kijun_period",   26),
                    senkou_b_period = ic.get("senkou_b_period", 52),
                    displacement    = ic.get("displacement",   26),
                    chikou_shift    = ic.get("chikou_shift",   26),
                ),
                detector=DetectorConfig(
                    cooldown_minutes = cfg.get("signals", {}).get("cooldown_minutes", 30),
                    cloud_filter     = cloud_on,
                ),
                warmup_candles=100,
                buffer_size=300,
            )
            try:
                signals = BacktestEngine(bt_config).run(
                    symbol=bt_symbol,
                    timeframe=bt_tf,
                    candles=candles_bt,
                    enabled_signals=set(selected_sigs) or None,
                )
            except Exception as exc:
                st.error(f"Backtest error: {exc}")
                signals = []

        if not signals:
            st.warning("No signals generated. Try more candles or fewer filters.")
        else:
            buys  = [s for s in signals if s.direction == "BUY"]
            sells = [s for s in signals if s.direction == "SELL"]
            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("Total Signals", len(signals))
            rc2.metric("BUY",           len(buys))
            rc3.metric("SELL",          len(sells))

            # Build table
            rows = []
            for sig in signals:
                row = {
                    "Timestamp":   sig.timestamp.strftime("%Y-%m-%d %H:%M"),
                    "Direction":   sig.direction,
                    "Signal Type": sig.signal_type,
                    "Price":       round(sig.price, 5),
                }
                row.update({
                    k: round(v, 5) if isinstance(v, float) else v
                    for k, v in sig.details.items()
                })
                rows.append(row)
            df_sig = pd.DataFrame(rows)

            # Direction filter
            dir_filter = st.multiselect(
                "Filter by Direction", ["BUY", "SELL"], default=["BUY", "SELL"]
            )
            st.dataframe(
                df_sig[df_sig["Direction"].isin(dir_filter)],
                width="stretch",
                hide_index=True,
            )

            st.subheader("Signals by Type")
            counts = (
                df_sig.groupby("Signal Type").size()
                .reset_index(name="Count")
                .set_index("Signal Type")
            )
            st.bar_chart(counts["Count"])

            st.download_button(
                "Download CSV",
                data=df_sig.to_csv(index=False).encode("utf-8"),
                file_name=f"backtest_{bt_symbol}_{bt_tf}.csv",
                mime="text/csv",
            )

# ─────────────────────────────────────────────────────────────────────────────
#  Page: Signal Log
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Signal Log":
    st.title("Signal Log")

    output_dir = cfg.get("backtest", {}).get("output_dir", "./backtest_results")
    results_dir = (ROOT / output_dir).resolve()
    csv_files   = sorted(results_dir.glob("*.csv"), reverse=True)

    if not csv_files:
        st.info(f"No CSV files found in {results_dir}. Run a backtest first.")
    else:
        selected_file = st.selectbox("Result file", [f.name for f in csv_files])
        df_log = pd.read_csv(results_dir / selected_file)

        fc1, fc2, fc3 = st.columns(3)
        dirs_sel = stypes_sel = pairs_sel = None

        with fc1:
            if "direction" in df_log.columns:
                dirs_sel = st.multiselect(
                    "Direction",
                    df_log["direction"].unique().tolist(),
                    default=df_log["direction"].unique().tolist(),
                )
        with fc2:
            if "signal_type" in df_log.columns:
                stypes_sel = st.multiselect(
                    "Signal Type",
                    df_log["signal_type"].unique().tolist(),
                    default=df_log["signal_type"].unique().tolist(),
                )
        with fc3:
            if "pair" in df_log.columns:
                pairs_sel = st.multiselect(
                    "Pair",
                    df_log["pair"].unique().tolist(),
                    default=df_log["pair"].unique().tolist(),
                )

        mask = pd.Series([True] * len(df_log), index=df_log.index)
        if dirs_sel   is not None: mask &= df_log["direction"].isin(dirs_sel)
        if stypes_sel is not None: mask &= df_log["signal_type"].isin(stypes_sel)
        if pairs_sel  is not None: mask &= df_log["pair"].isin(pairs_sel)

        df_show = df_log[mask]
        st.dataframe(df_show, width="stretch", hide_index=True)

        st.subheader("Summary")
        s1, s2, s3 = st.columns(3)
        s1.metric("Signals shown", len(df_show))
        if "direction" in df_show.columns:
            s2.metric("BUY",  int((df_show["direction"] == "BUY").sum()))
            s3.metric("SELL", int((df_show["direction"] == "SELL").sum()))

# ─────────────────────────────────────────────────────────────────────────────
#  Page: Configuration
# ─────────────────────────────────────────────────────────────────────────────

elif page == "Configuration":
    st.title("Configuration")
    st.caption(f"Editing: {CONFIG_PATH}")

    # Work on a fresh copy so edits don't bleed into the cached version
    cfg_edit = load_config()

    # General
    st.subheader("General")
    g = cfg_edit.setdefault("general", {})
    g["log_level"] = st.selectbox(
        "Log Level",
        ["DEBUG", "INFO", "WARNING", "ERROR"],
        index=["DEBUG", "INFO", "WARNING", "ERROR"].index(g.get("log_level", "INFO")),
    )
    g["dry_run"] = st.checkbox(
        "Dry Run (log only — no Discord messages)",
        value=bool(g.get("dry_run", True)),
    )

    st.divider()

    # Ichimoku
    st.subheader("Ichimoku Parameters")
    ic = cfg_edit.setdefault("ichimoku", {})
    c1, c2, c3, c4, c5 = st.columns(5)
    ic["tenkan_period"]   = int(c1.number_input("Tenkan",       value=int(ic.get("tenkan_period",   9)),  min_value=1))
    ic["kijun_period"]    = int(c2.number_input("Kijun",        value=int(ic.get("kijun_period",   26)),  min_value=1))
    ic["senkou_b_period"] = int(c3.number_input("Senkou B",     value=int(ic.get("senkou_b_period", 52)), min_value=1))
    ic["displacement"]    = int(c4.number_input("Displacement", value=int(ic.get("displacement",   26)),  min_value=1))
    ic["chikou_shift"]    = int(c5.number_input("Chikou Shift", value=int(ic.get("chikou_shift",   26)),  min_value=1))

    st.divider()

    # Signals
    st.subheader("Signal Settings")
    sg = cfg_edit.setdefault("signals", {})
    sg["cooldown_minutes"]   = int(st.number_input(
        "Cooldown (minutes)", value=int(sg.get("cooldown_minutes", 30)), min_value=0
    ))
    sg["cloud_filter"]       = st.checkbox("Cloud Filter",        value=bool(sg.get("cloud_filter", True)))
    sg["strong_signal_only"] = st.checkbox("Strong Signal Only",  value=bool(sg.get("strong_signal_only", False)))

    st.divider()

    # Pairs
    st.subheader("Pairs")
    for i, pair in enumerate(cfg_edit.get("pairs", [])):
        with st.expander(pair["symbol"]):
            pair["symbol"] = st.text_input("Symbol", value=pair["symbol"], key=f"sym_{i}")
            pair["timeframes"] = st.multiselect(
                "Timeframes",
                ["M1", "M5", "M15", "M30", "H1", "H4", "D1"],
                default=pair.get("timeframes", ["H1"]),
                key=f"tf_{i}",
            )
            _all_sigs = sorted(SignalDetector.ALL_SIGNALS)
            _valid_defaults = [s for s in pair.get("enabled_signals", []) if s in _all_sigs]
            pair["enabled_signals"] = st.multiselect(
                "Enabled Signals",
                _all_sigs,
                default=_valid_defaults,
                key=f"sig_{i}",
            )

    st.divider()
    if st.button("Save Configuration", type="primary"):
        save_config(cfg_edit)
        st.cache_data.clear()
        st.success("config.yaml saved.")
