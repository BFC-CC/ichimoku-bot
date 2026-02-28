"""
gui/chart.py
────────────────────────────────────────────────────────────────────────────
Plotly Ichimoku chart builder.

Usage
-----
    from gui.chart import build_ichimoku_chart
    fig = build_ichimoku_chart(candles_df, ichi_df)
    st.plotly_chart(fig, use_container_width=True)
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


def build_ichimoku_chart(
    candles: pd.DataFrame,
    ichi: pd.DataFrame,
) -> go.Figure:
    """
    Build an interactive Plotly chart with full Ichimoku overlay.

    Parameters
    ----------
    candles : DataFrame with columns open, high, low, close and DatetimeIndex
    ichi    : DataFrame with columns tenkan, kijun, senkou_a, senkou_b, chikou
              (same index as candles)

    Returns
    -------
    go.Figure
    """
    fig = go.Figure()

    # ── Candlestick ───────────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=candles.index,
        open=candles["open"],
        high=candles["high"],
        low=candles["low"],
        close=candles["close"],
        name="Price",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
        increasing_fillcolor="#26a69a",
        decreasing_fillcolor="#ef5350",
    ))

    # ── Tenkan-sen (red, thin) ────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=ichi.index, y=ichi["tenkan"],
        name="Tenkan", mode="lines",
        line=dict(color="#e53935", width=1),
    ))

    # ── Kijun-sen (blue, slightly thicker) ───────────────────────────────────
    fig.add_trace(go.Scatter(
        x=ichi.index, y=ichi["kijun"],
        name="Kijun", mode="lines",
        line=dict(color="#1e88e5", width=1.5),
    ))

    # ── Chikou Span (purple, dotted) ──────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=ichi.index, y=ichi["chikou"],
        name="Chikou", mode="lines",
        line=dict(color="#ab47bc", width=1, dash="dot"),
    ))

    # ── Kumo cloud (Senkou A & B with fill) ───────────────────────────────────
    common_idx = (
        ichi["senkou_a"].dropna().index
        .intersection(ichi["senkou_b"].dropna().index)
    )

    if len(common_idx) > 0:
        sa = ichi.loc[common_idx, "senkou_a"]
        sb = ichi.loc[common_idx, "senkou_b"]

        # Senkou B drawn first (base of the fill)
        fig.add_trace(go.Scatter(
            x=common_idx, y=sb,
            name="Senkou B", mode="lines",
            line=dict(color="rgba(239,83,80,0.8)", width=1),
            fill=None,
        ))

        # Senkou A fills down to Senkou B
        fig.add_trace(go.Scatter(
            x=common_idx, y=sa,
            name="Senkou A", mode="lines",
            line=dict(color="rgba(38,166,154,0.8)", width=1),
            fill="tonexty",
            fillcolor="rgba(38,166,154,0.15)",
        ))

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        height=600,
        margin=dict(l=40, r=40, t=40, b=40),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="right",  x=1,
        ),
        xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.08)"),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.08)"),
    )

    return fig
