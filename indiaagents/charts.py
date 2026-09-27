"""
Professional price chart for reports & dashboard — matplotlib (Agg), dark
fintech theme, self-contained PNG (base64-embeddable in HTML reports).
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402
import pandas as pd  # noqa: E402

from .data.market import _sma  # noqa: E402

# Dark fintech palette
BG = "#0b1220"
PANEL = "#101a2e"
GRID = "#1e2a44"
TEXT = "#dbe4f3"
MUTED = "#7e8ca8"
UP = "#22c55e"
DOWN = "#ef4444"
ACCENT = "#38bdf8"
BAND = "#6366f1"


def build_price_chart(df: pd.DataFrame, name: str, ticker: str,
                      decision: str = "", save_dir: Path | None = None) -> dict:
    """3-panel chart: price+SMA+BB / volume / RSI. Returns {'png': bytes,
    'b64': str, 'path': str|None}."""
    d = df.tail(180).copy()
    d.index = pd.to_datetime(d.index)
    close = d["Close"]

    sma50 = _sma(close, 50)
    sma200 = _sma(close, 200)
    mid = _sma(close, 20)
    std = close.rolling(20).std()
    ub, lb = mid + 2 * std, mid - 2 * std
    rsi_series = _rsi_series(close)

    fig, (ax1, ax2, ax3) = plt.subplots(
        3, 1, figsize=(11.5, 7.6), sharex=True, dpi=150,
        gridspec_kw={"height_ratios": [3.2, 1, 1], "hspace": 0.06})
    fig.patch.set_facecolor(BG)
    last = float(close.iloc[-1])
    first = float(close.iloc[0])
    chg = (last - first) / first * 100

    # ---- Panel 1: price -----------------------------------------------------
    up = d["Close"] >= d["Close"].shift(1)
    ax1.vlines(d.index, d["Low"], d["High"], color=np_where(up, UP, DOWN, d),
               linewidth=0.8, alpha=0.85)
    ax1.fill_between(d.index, lb, ub, color=BAND, alpha=0.10, label="Bollinger (20,2)")
    ax1.plot(d.index, mid, color=BAND, lw=1.0, alpha=0.75, label="20-SMA")
    if sma50.notna().any():
        ax1.plot(d.index, sma50, color="#f59e0b", lw=1.3, label="50-SMA")
    if sma200.notna().any():
        ax1.plot(d.index, sma200, color="#a78bfa", lw=1.3, label="200-SMA")
    ax1.scatter([d.index[-1]], [last], s=42, zorder=5,
                color=UP if chg >= 0 else DOWN, edgecolor="white", linewidth=1.2)
    ax1.annotate(f"  ₹{last:,.0f}", fontsize=10.5,
                 fontweight="bold", color=TEXT, va="center",
                 xycoords=("axes fraction", "data"), xy=(1.005, last))
    dec_color = {"BUY": UP, "SELL": DOWN, "HOLD": "#eab308"}.get(decision, ACCENT)
    title = f"{name}  ({ticker})   ·   {chg:+.1f}% over window"
    if decision:
        title += f"   ·   AI VERDICT: {decision}"
    ax1.set_title(title, fontsize=13, fontweight="bold", color=dec_color,
                  loc="left", pad=10)
    ax1.legend(loc="upper left", frameon=False, fontsize=8.5,
               labelcolor=TEXT, ncol=4)

    # ---- Panel 2: volume ----------------------------------------------------
    vols = d["Volume"] / 1e6
    ax2.bar(d.index, vols, width=1.0,
            color=[UP if u else DOWN for u in up.fillna(True)],
            alpha=0.65)
    ax2.plot(d.index, vols.rolling(20).mean(), color=ACCENT, lw=1.1, label="20-day avg")
    ax2.legend(loc="upper left", frameon=False, fontsize=8, labelcolor=TEXT)
    ax2.set_ylabel("Vol (M)", fontsize=8.5, color=MUTED)

    # ---- Panel 3: RSI --------------------------------------------------------
    ax3.plot(d.index, rsi_series, color=ACCENT, lw=1.3)
    ax3.axhline(70, color=DOWN, lw=0.8, ls="--", alpha=0.6)
    ax3.axhline(30, color=UP, lw=0.8, ls="--", alpha=0.6)
    ax3.fill_between(d.index, 70, rsi_series.where(rsi_series > 70), color=DOWN, alpha=0.25)
    ax3.fill_between(d.index, 30, rsi_series.where(rsi_series < 30), color=UP, alpha=0.25)
    ax3.set_ylim(0, 100)
    ax3.set_ylabel("RSI 14", fontsize=8.5, color=MUTED)
    ax3.text(0.005, 0.86, "overbought 70", transform=ax3.transAxes, fontsize=7.5,
             color=DOWN, alpha=0.9)
    ax3.text(0.005, 0.06, "oversold 30", transform=ax3.transAxes, fontsize=7.5,
             color=UP, alpha=0.9)

    for ax in (ax1, ax2, ax3):
        ax.set_facecolor(PANEL)
        ax.grid(True, color=GRID, linewidth=0.5, alpha=0.7)
        ax.tick_params(colors=MUTED, labelsize=8.5)
        for s in ax.spines.values():
            s.set_visible(False)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    fig.align_ylabels()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    png = buf.getvalue()

    path = None
    if save_dir:
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / "chart.png"
        path.write_bytes(png)

    return {"png": png, "b64": base64.b64encode(png).decode(), "path": str(path) if path else None}


def _rsi_series(close: pd.Series) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - 100 / (1 + rs)


def np_where(up: pd.Series, up_color: str, down_color: str, d: pd.DataFrame):
    import numpy as np
    return np.where(up.fillna(True), up_color, down_color)
