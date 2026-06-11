#!/usr/bin/env python3
"""Fetch prices, score watchlist stocks, and render the investment dashboard."""

from __future__ import annotations

import argparse
import html
import json
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import matplotlib
import matplotlib.font_manager
import matplotlib.lines as mlines
import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd
import yfinance as yf

from scoring import ScoreResult, add_indicators, score_stock


ROOT_DIR = Path(__file__).resolve().parents[1]
WATCHLIST_PATH = ROOT_DIR / "watchlist.csv"
DASHBOARD_PATH = ROOT_DIR / "dashboard.html"
INDEX_PATH = ROOT_DIR / "index.html"
REPORT_PATH = ROOT_DIR / "report.md"
CHARTS_DIR = ROOT_DIR / "charts"
DATA_DIR = ROOT_DIR / "data"
REPORTS_DIR = ROOT_DIR / "reports"
CHART_FONT_FAMILY = "DejaVu Sans"


@dataclass
class StockSummary:
    code: str
    name: str
    memo: str
    list_name: str
    symbol: str
    latest_date: str | None
    close: float | None
    rsi: float | None
    volume_ratio: float | None
    drawdown: float | None
    return5d: float | None
    chart_paths: dict[str, str]
    data_path: str | None
    score: ScoreResult
    error: str | None = None


def configure_fonts() -> None:
    global CHART_FONT_FAMILY
    candidates = [
        "Hiragino Sans",
        "Hiragino Kaku Gothic ProN",
        "Yu Gothic",
        "Noto Sans CJK JP",
        "Arial Unicode MS",
    ]
    available = {font.name for font in matplotlib.font_manager.fontManager.ttflist}
    for family in candidates:
        if family in available:
            CHART_FONT_FAMILY = family
            matplotlib.rcParams["font.family"] = family
            break
    matplotlib.rcParams["axes.unicode_minus"] = False


def fmt_number(value: float | None, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value:,.{digits}f}"


def fmt_percent(value: float | None, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{value * 100:.{digits}f}%"


def to_symbol(code: str) -> str:
    code = str(code).strip()
    return code if "." in code else f"{code}.T"


def read_watchlist(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"watchlist.csv not found: {path}")
    df = pd.read_csv(path, dtype={"code": str, "name": str, "memo": str})
    required = {"code", "name", "memo"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"watchlist.csv is missing columns: {', '.join(sorted(missing))}")
    if "list" not in df.columns:
        df["list"] = "監視銘柄"
    return df.fillna("")


def normalize_price_data(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw.empty:
        return raw

    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        if symbol in df.columns.get_level_values(-1):
            df = df.xs(symbol, axis=1, level=-1)
        else:
            df.columns = df.columns.get_level_values(0)

    required = ["Open", "High", "Low", "Close", "Volume"]
    df = df[[col for col in required if col in df.columns]].copy()
    for col in required:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df[df["Volume"].fillna(0) >= 0]
    df.index = pd.to_datetime(df.index)
    df.index.name = "Date"
    return df.sort_index()


def fetch_prices(symbol: str, period: str) -> pd.DataFrame:
    raw = yf.download(
        symbol,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    return normalize_price_data(raw, symbol)


def save_price_data(df: pd.DataFrame, code: str) -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{code}.csv"
    df.to_csv(path, encoding="utf-8")
    return path.relative_to(ROOT_DIR).as_posix()


def chart_style() -> dict:
    return mpf.make_mpf_style(
        base_mpf_style="yahoo",
        rc={
            "font.family": CHART_FONT_FAMILY,
            "axes.unicode_minus": False,
            "font.size": 12,
            "axes.labelsize": 12,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "legend.fontsize": 12,
        },
    )


def make_chart(df: pd.DataFrame, code: str, name: str, output_dir: Path, filename: str, label: str, trading_days: int) -> str:
    chart_df = df.tail(trading_days).copy()
    addplots = []
    ma_styles = [("MA5", "#e4572e", "MA5"), ("MA25", "#2e86ab", "MA25"), ("MA75", "#4f772d", "MA75")]
    legend_handles = []
    for column, color, label_name in ma_styles:
        if column in chart_df and chart_df[column].notna().any():
            addplots.append(mpf.make_addplot(chart_df[column], color=color, width=1.8))
            legend_handles.append(mlines.Line2D([], [], color=color, linewidth=2.2, label=label_name))
    if "RSI14" in chart_df and chart_df["RSI14"].notna().any():
        addplots.append(mpf.make_addplot(chart_df["RSI14"], panel=2, color="#7b2cbf", width=1.4, ylabel="RSI"))
    output_path = output_dir / filename
    fig, axes = mpf.plot(
        chart_df,
        type="candle",
        style=chart_style(),
        volume=True,
        addplot=addplots if addplots else None,
        ylabel="",
        ylabel_lower="Volume",
        panel_ratios=(4, 1.2, 1),
        figsize=(14, 9),
        tight_layout=True,
        returnfig=True,
    )
    if legend_handles:
        axes[0].legend(handles=legend_handles, loc="upper left", frameon=True, facecolor="white", framealpha=0.85)
    fig.savefig(str(output_path), dpi=160, bbox_inches="tight")
    plt.close(fig)
    return output_path.relative_to(ROOT_DIR).as_posix()


def make_charts(df: pd.DataFrame, code: str, name: str, output_dir: Path) -> dict[str, str]:
    chart_paths = {
        "1m": make_chart(df, code, name, output_dir, f"{code}_1m.png", "1m", 22),
        "3m": make_chart(df, code, name, output_dir, f"{code}_3m.png", "3m", 66),
        "6m": make_chart(df, code, name, output_dir, f"{code}_6m.png", "6m", 132),
    }
    chart_paths["latest"] = make_chart(df, code, name, output_dir, f"{code}.png", "latest", 132)
    return chart_paths


def empty_score(label: str = "判定不可") -> ScoreResult:
    return ScoreResult(
        total_score=0,
        signal_label=label,
        trend_score=0,
        breakout_score=0,
        volume_score=0,
        rsi_score=0,
        reversal_score=0,
        risk_penalty=0,
        reversal_label=label,
        comments=["取得または判定に失敗"],
        reasons={},
    )


def summarize_stock(row: pd.Series, output_dir: Path, period: str) -> StockSummary:
    code = str(row["code"]).strip()
    name = str(row["name"]).strip()
    memo = str(row["memo"]).strip()
    list_name = str(row.get("list", "監視銘柄")).strip() or "監視銘柄"
    symbol = to_symbol(code)

    try:
        df = fetch_prices(symbol, period)
        if len(df) < 20:
            raise ValueError(f"indicator calculation needs at least 20 rows, got {len(df)}")
        df = add_indicators(df)
        data_path = save_price_data(df, code)
        score = score_stock(df)
        chart_paths = make_charts(df, code, name, output_dir)
        latest = df.iloc[-1]

        return StockSummary(
            code=code,
            name=name,
            memo=memo,
            list_name=list_name,
            symbol=symbol,
            latest_date=latest.name.strftime("%Y-%m-%d"),
            close=float(latest["Close"]),
            rsi=float(latest["RSI14"]) if pd.notna(latest.get("RSI14")) else None,
            volume_ratio=float(latest["VolumeRatio"]) if pd.notna(latest.get("VolumeRatio")) else None,
            drawdown=float(latest["DrawdownFrom52wHigh"]) if pd.notna(latest.get("DrawdownFrom52wHigh")) else None,
            return5d=float(latest["Return5d"]) if pd.notna(latest.get("Return5d")) else None,
            chart_paths=chart_paths,
            data_path=data_path,
            score=score,
        )
    except Exception as exc:
        return StockSummary(
            code=code,
            name=name,
            memo=memo,
            list_name=list_name,
            symbol=symbol,
            latest_date=None,
            close=None,
            rsi=None,
            volume_ratio=None,
            drawdown=None,
            return5d=None,
            chart_paths={},
            data_path=None,
            score=empty_score(),
            error=str(exc),
        )


def badge_class(item: StockSummary) -> str:
    if item.error:
        return "muted"
    if item.score.total_score >= 75:
        return "strong"
    if item.score.total_score >= 50:
        return "watch"
    if item.score.total_score >= 35:
        return "weak"
    return "exclude"


def score_class(item: StockSummary) -> str:
    score = item.score.total_score
    if item.error:
        return "score-muted"
    if score >= 75:
        return "score-strong"
    if score >= 65:
        return "score-good"
    if score >= 50:
        return "score-watch"
    if score >= 35:
        return "score-weak"
    return "score-exclude"


def render_reason_list(reasons: list[str]) -> str:
    if not reasons:
        return "<li>該当なし</li>"
    return "".join(f"<li>{html.escape(reason)}</li>" for reason in reasons)


def render_reason_group(title: str, reasons: list[str]) -> str:
    return f"""
    <details>
      <summary>{html.escape(title)}</summary>
      <ul>{render_reason_list(reasons)}</ul>
    </details>
    """


def render_dashboard(summaries: list[StockSummary], generated_on: str, chart_date: str) -> str:
    sorted_items = sorted(summaries, key=lambda item: item.score.total_score, reverse=True)
    list_names = []
    for item in summaries:
        for list_name in item.list_name.split("|"):
            list_name = list_name.strip()
            if list_name and list_name not in list_names:
                list_names.append(list_name)
    list_buttons = '<button type="button" class="list-tab active" data-list="all">全部</button>'
    list_buttons += "".join(
        f'<button type="button" class="list-tab" data-list="{html.escape(list_name)}">{html.escape(list_name)}</button>'
        for list_name in list_names
    )
    rows = []
    for item in sorted_items:
        default_chart = item.chart_paths.get("3m") or item.chart_paths.get("latest")
        chart_data = "".join(
            f'<span data-chart-code="{html.escape(item.code)}" data-chart-range="{html.escape(label)}" '
            f'data-chart-src="{html.escape(path)}"></span>'
            for label, path in item.chart_paths.items()
            if label in {"1m", "3m", "6m"}
        )
        chart = (
            f'<img class="stock-chart" id="chart-{html.escape(item.code)}" data-code="{html.escape(item.code)}" '
            f'src="{html.escape(default_chart)}" alt="{html.escape(item.code)} chart">{chart_data}'
            if default_chart
            else '<div class="chart-placeholder">チャートなし</div>'
        )
        score = item.score
        reasons = score.reasons
        reason_groups = "".join(
            [
                render_reason_group("トレンド", reasons.get("trend", [])),
                render_reason_group("新高値・ブレイク", reasons.get("breakout", [])),
                render_reason_group("出来高", reasons.get("volume", [])),
                render_reason_group("RSI", reasons.get("rsi", [])),
                render_reason_group("反転初動", reasons.get("reversal", [])),
                render_reason_group("リスク減点", reasons.get("risk", [])),
            ]
        )
        comments = " / ".join(score.comments)
        error = f'<p class="error">取得エラー: {html.escape(item.error)}</p>' if item.error else ""
        detail_metrics = f"""
              <dl class="metrics">
                <div><dt>終値</dt><dd>{fmt_number(item.close, 0)}</dd></div>
                <div><dt>RSI14</dt><dd>{fmt_number(item.rsi, 1)}</dd></div>
                <div><dt>出来高倍率</dt><dd>{fmt_number(item.volume_ratio, 2)}x</dd></div>
                <div><dt>52週高値から</dt><dd>{fmt_percent(item.drawdown)}</dd></div>
                <div><dt>5日騰落率</dt><dd>{fmt_percent(item.return5d)}</dd></div>
                <div><dt>基準日</dt><dd>{html.escape(item.latest_date or "-")}</dd></div>
                <div><dt>トレンド</dt><dd>{score.trend_score}/20</dd></div>
                <div><dt>新高値</dt><dd>{score.breakout_score}/20</dd></div>
                <div><dt>出来高</dt><dd>{score.volume_score}/15</dd></div>
                <div><dt>RSI</dt><dd>{score.rsi_score}/15</dd></div>
                <div><dt>反転初動</dt><dd>{score.reversal_score}/25</dd></div>
                <div><dt>リスク</dt><dd>{score.risk_penalty}</dd></div>
              </dl>
        """
        rows.append(
            f"""
            <section class="stock {badge_class(item)}"
              data-list="{html.escape(item.list_name)}"
              data-total="{score.total_score}"
              data-reversal="{score.reversal_score}"
              data-breakout="{score.breakout_score}"
              data-volume="{score.volume_score}"
              data-risk="{score.risk_penalty}">
              <div class="stock-head">
                <div>
                  <h2>{html.escape(item.name)}</h2>
                  <p>{html.escape(item.code)} / {html.escape(item.symbol)} / {html.escape(item.list_name)}{(" / " + html.escape(item.memo)) if item.memo else ""}</p>
                </div>
                <div class="score {score_class(item)}">{score.total_score}</div>
              </div>
              <div class="label-row">
                <span>{html.escape(score.signal_label)}</span>
                <span>{html.escape(score.reversal_label)}</span>
              </div>
              <div class="chart">{chart}</div>
              <details class="stock-detail">
                <summary>詳細スコア・根拠</summary>
                <div class="comment">{html.escape(comments)}</div>
                {detail_metrics}
                <div class="reason-groups">{reason_groups}</div>
              </details>
              {error}
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Investment Watchlist Dashboard</title>
  <style>
    :root {{
      --bg: #edf6ff;
      --text: #17202a;
      --muted: #65717f;
      --line: #d8dde3;
      --panel: #ffffff;
      --strong: #0b7a53;
      --watch: #b26b00;
      --weak: #9c2f2f;
      --exclude: #6b7280;
      --accent: #214f7a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        linear-gradient(rgba(242, 248, 255, 0.72), rgba(242, 248, 255, 0.72)),
        linear-gradient(90deg, rgba(33, 79, 122, 0.045) 1px, transparent 1px),
        linear-gradient(rgba(33, 79, 122, 0.045) 1px, transparent 1px),
        var(--bg);
      background-size: auto, 28px 28px, 28px 28px, auto;
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    header {{
      padding: 22px clamp(16px, 4vw, 48px);
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(14px);
    }}
    h1 {{ margin: 0; font-size: clamp(24px, 3vw, 34px); letter-spacing: 0; }}
    header p {{ margin: 6px 0 0; color: var(--muted); }}
    .toolbar {{
      position: sticky;
      top: 0;
      z-index: 10;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px clamp(16px, 4vw, 48px);
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.96);
      backdrop-filter: blur(10px);
    }}
    .control-group {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .control-group span {{ color: var(--muted); font-size: 13px; font-weight: 700; }}
    button {{
      appearance: none;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--muted);
      border-radius: 8px;
      min-width: 52px;
      height: 34px;
      padding: 0 10px;
      font-weight: 700;
      cursor: pointer;
    }}
    button.active {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
    main {{
      display: grid;
      gap: 16px;
      padding: 20px clamp(16px, 4vw, 48px) 40px;
    }}
    main.grid-1 {{ grid-template-columns: 1fr; }}
    main.grid-2 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    main.grid-4 {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    .stock {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-left: 6px solid var(--muted);
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 10px 28px rgba(23, 32, 42, 0.08);
    }}
    .stock.strong {{ border-left-color: var(--strong); }}
    .stock.watch {{ border-left-color: var(--watch); }}
    .stock.weak {{ border-left-color: var(--weak); }}
    .stock.exclude {{ border-left-color: var(--exclude); }}
    .stock-head {{
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px 8px;
    }}
    h2 {{ margin: 0; font-size: 20px; letter-spacing: 0; }}
    .stock-head p {{ margin: 4px 0 0; color: var(--muted); font-size: 13px; }}
    .score {{
      min-width: 50px;
      height: 50px;
      display: grid;
      place-items: center;
      border-radius: 8px;
      background: var(--accent);
      color: #fff;
      font-size: 24px;
      font-weight: 800;
    }}
    .score-strong {{ background: #0b7a53; }}
    .score-good {{ background: #1570a6; }}
    .score-watch {{ background: #b26b00; }}
    .score-weak {{ background: #b8492f; }}
    .score-exclude {{ background: #6b7280; }}
    .score-muted {{ background: #9ca3af; }}
    .label-row {{ display: flex; flex-wrap: wrap; gap: 8px; padding: 0 16px 10px; }}
    .label-row span {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 4px 8px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }}
    .chart {{ border-top: 1px solid var(--line); background: #fbfbfb; }}
    .chart img {{ display: block; width: 100%; height: auto; }}
    .chart-placeholder {{ min-height: 220px; display: grid; place-items: center; color: var(--muted); }}
    .stock-detail {{
      border-top: 1px solid var(--line);
      padding: 0;
    }}
    .stock-detail > summary {{
      cursor: pointer;
      padding: 11px 16px;
      font-weight: 800;
      color: var(--accent);
      list-style-position: inside;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin: 0;
      padding: 12px 16px 16px;
      gap: 10px 16px;
    }}
    .metrics div {{ min-width: 0; }}
    dt {{ color: var(--muted); font-size: 12px; }}
    dd {{ margin: 2px 0 0; font-weight: 650; overflow-wrap: anywhere; }}
    .comment {{ border-top: 1px solid var(--line); padding: 12px 16px; font-weight: 700; }}
    .reason-groups {{ border-top: 1px solid var(--line); padding: 10px 16px 16px; }}
    .reason-groups details {{ border-bottom: 1px solid #edf0f2; padding: 7px 0; }}
    .reason-groups details:last-child {{ border-bottom: 0; }}
    .reason-groups summary {{ cursor: pointer; font-weight: 700; font-size: 13px; }}
    ul {{ margin: 6px 0 0; padding-left: 18px; color: var(--muted); font-size: 13px; }}
    .error {{ margin: 0; padding: 0 16px 16px; color: var(--weak); font-size: 13px; }}
    @media (max-width: 520px) {{
      main.grid-1,
      main.grid-2,
      main.grid-4 {{ grid-template-columns: 1fr; }}
      .metrics {{ grid-template-columns: 1fr; }}
      .toolbar {{ align-items: stretch; }}
      .control-group {{ width: 100%; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Investment Watchlist Dashboard</h1>
    <p>Generated: {html.escape(generated_on)} / Chart folder: charts/{html.escape(chart_date)} / スコアは売買推奨ではなく監視優先度です。</p>
  </header>
  <nav class="toolbar" aria-label="Dashboard controls">
    <div class="control-group" aria-label="Watchlist filter">
      <span>リスト</span>
      {list_buttons}
    </div>
    <div class="control-group" aria-label="Chart range">
      <span>チャート期間</span>
      <button type="button" class="range-tab" data-range="1m">1M</button>
      <button type="button" class="range-tab active" data-range="3m">3M</button>
      <button type="button" class="range-tab" data-range="6m">6M</button>
    </div>
    <div class="control-group" aria-label="Grid columns">
      <span>列数</span>
      <button type="button" class="grid-tab" data-grid="grid-1">1</button>
      <button type="button" class="grid-tab active" data-grid="grid-2">2</button>
      <button type="button" class="grid-tab" data-grid="grid-4">4</button>
    </div>
    <div class="control-group" aria-label="Sort stocks">
      <span>並び替え</span>
      <button type="button" class="sort-tab active" data-sort="total" data-order="desc">総合</button>
      <button type="button" class="sort-tab" data-sort="reversal" data-order="desc">反転</button>
      <button type="button" class="sort-tab" data-sort="breakout" data-order="desc">新高値</button>
      <button type="button" class="sort-tab" data-sort="volume" data-order="desc">出来高</button>
      <button type="button" class="sort-tab" data-sort="risk" data-order="asc">リスク</button>
    </div>
  </nav>
  <main id="stock-list" class="grid-2">
    {''.join(rows)}
  </main>
  <script>
    function visibleAnchorCard() {{
      const viewportAnchor = window.innerHeight * 0.5;
      const cards = Array.from(document.querySelectorAll(".stock:not([hidden])"));
      let best = cards[0] || null;
      let bestDistance = Number.POSITIVE_INFINITY;
      cards.forEach((card) => {{
        const rect = card.getBoundingClientRect();
        const distance = Math.abs(rect.top + rect.height / 2 - viewportAnchor);
        if (distance < bestDistance) {{
          best = card;
          bestDistance = distance;
        }}
      }});
      if (!best) return null;
      return {{
        card: best,
      }};
    }}

    function restoreAnchor(anchor) {{
      if (!anchor || !anchor.card || anchor.card.hidden) return;
      requestAnimationFrame(() => {{
        anchor.card.scrollIntoView({{ block: "center", inline: "nearest", behavior: "auto" }});
      }});
    }}

    document.querySelectorAll(".range-tab").forEach((button) => {{
      button.addEventListener("click", () => {{
        const range = button.dataset.range;
        document.querySelectorAll(".stock-chart").forEach((image) => {{
          const source = document.querySelector(`[data-chart-code="${{image.dataset.code}}"][data-chart-range="${{range}}"]`);
          if (source) image.src = source.dataset.chartSrc;
        }});
        document.querySelectorAll(".range-tab").forEach((tab) => tab.classList.toggle("active", tab === button));
      }});
    }});

    document.querySelectorAll(".list-tab").forEach((button) => {{
      button.addEventListener("click", () => {{
        const anchor = visibleAnchorCard();
        const listName = button.dataset.list;
        document.querySelectorAll(".stock").forEach((card) => {{
          const lists = (card.dataset.list || "").split("|");
          card.hidden = listName !== "all" && !lists.includes(listName);
        }});
        document.querySelectorAll(".list-tab").forEach((tab) => tab.classList.toggle("active", tab === button));
        restoreAnchor(anchor);
      }});
    }});

    document.querySelectorAll(".grid-tab").forEach((button) => {{
      button.addEventListener("click", () => {{
        const anchor = visibleAnchorCard();
        const list = document.getElementById("stock-list");
        list.classList.remove("grid-1", "grid-2", "grid-4");
        list.classList.add(button.dataset.grid);
        document.querySelectorAll(".grid-tab").forEach((tab) => tab.classList.toggle("active", tab === button));
        restoreAnchor(anchor);
      }});
    }});

    document.querySelectorAll(".sort-tab").forEach((button) => {{
      button.addEventListener("click", () => {{
        const anchor = visibleAnchorCard();
        const key = button.dataset.sort;
        const order = button.dataset.order === "asc" ? 1 : -1;
        const list = document.getElementById("stock-list");
        const cards = Array.from(list.querySelectorAll(".stock"));
        cards.sort((a, b) => {{
          const av = Number(a.dataset[key] || 0);
          const bv = Number(b.dataset[key] || 0);
          return (av - bv) * order;
        }});
        cards.forEach((card) => list.appendChild(card));
        document.querySelectorAll(".sort-tab").forEach((tab) => tab.classList.toggle("active", tab === button));
        restoreAnchor(anchor);
      }});
    }});
  </script>
</body>
</html>
"""


def ranking_lines(items: list[StockSummary], key: str, limit: int | None = None) -> str:
    if limit is not None:
        items = items[:limit]
    if not items:
        return "- なし"

    def value(item: StockSummary) -> str:
        score = item.score
        if key == "total":
            return f"{score.total_score}点 / {score.signal_label}"
        if key == "reversal":
            return f"{score.reversal_score}/25点 / {score.reversal_label}"
        if key == "breakout":
            return f"{score.breakout_score}/20点"
        if key == "volume":
            return f"{score.volume_score}/15点 / 出来高 {fmt_number(item.volume_ratio, 2)}x"
        if key == "risk":
            return f"{score.risk_penalty}点"
        return ""

    return "\n".join(
        f"- {value(item)}: {item.code} {item.name} [{item.list_name}] / {', '.join(item.score.comments)}"
        for item in items
    )


def render_report(summaries: list[StockSummary], generated_on: str) -> str:
    ok_items = [item for item in summaries if not item.error]
    errors = [item for item in summaries if item.error]
    total_ranked = sorted(ok_items, key=lambda item: item.score.total_score, reverse=True)
    reversal_ranked = sorted(ok_items, key=lambda item: item.score.reversal_score, reverse=True)
    breakout_ranked = sorted(ok_items, key=lambda item: item.score.breakout_score, reverse=True)
    volume_ranked = sorted(ok_items, key=lambda item: item.score.volume_score, reverse=True)
    risk_ranked = sorted(ok_items, key=lambda item: item.score.risk_penalty)
    exclude_items = [item for item in total_ranked if item.score.signal_label == "除外候補"]

    error_lines = "\n".join(f"- {item.code} {item.name}: {item.error}" for item in errors) if errors else "- なし"

    return f"""# 投資ダッシュボード レポート

Generated: {generated_on}

このスコアは売買推奨ではなく、監視優先度を決めるためのスコアです。

## 総合スコアランキング

{ranking_lines(total_ranked, "total")}

## 反転初動スコアランキング

{ranking_lines(reversal_ranked, "reversal")}

## 新高値ブレイク候補ランキング

{ranking_lines(breakout_ranked, "breakout")}

## 出来高急増ランキング

{ranking_lines(volume_ranked, "volume")}

## リスク減点が大きい銘柄一覧

{ranking_lines(risk_ranked, "risk")}

## 除外候補一覧

{ranking_lines(exclude_items, "total")}

## エラーで取得できなかった銘柄一覧

{error_lines}
"""


def write_outputs(summaries: list[StockSummary], chart_date: str) -> None:
    generated_on = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    dashboard_html = render_dashboard(summaries, generated_on, chart_date)
    DASHBOARD_PATH.write_text(dashboard_html, encoding="utf-8")
    INDEX_PATH.write_text(dashboard_html, encoding="utf-8")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    daily_report_dir = REPORTS_DIR / chart_date
    daily_report_dir.mkdir(parents=True, exist_ok=True)
    report = render_report(summaries, generated_on)
    REPORT_PATH.write_text(report, encoding="utf-8")
    (REPORTS_DIR / "report.md").write_text(report, encoding="utf-8")
    (daily_report_dir / "report.md").write_text(report, encoding="utf-8")

    score_rows = []
    for item in summaries:
        score_rows.append(
            {
                "code": item.code,
                "name": item.name,
                "memo": item.memo,
                "list": item.list_name,
                "symbol": item.symbol,
                "latest_date": item.latest_date,
                "total_score": item.score.total_score,
                "signal_label": item.score.signal_label,
                "reversal_label": item.score.reversal_label,
                "trend_score": item.score.trend_score,
                "breakout_score": item.score.breakout_score,
                "volume_score": item.score.volume_score,
                "rsi_score": item.score.rsi_score,
                "reversal_score": item.score.reversal_score,
                "risk_penalty": item.score.risk_penalty,
                "comments": item.score.comments,
                "reasons": item.score.reasons,
                "error": item.error,
            }
        )
    (DATA_DIR / "latest_scores.json").write_text(
        json.dumps(score_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def copy_latest_charts(output_dir: Path) -> None:
    latest_dir = CHARTS_DIR / "latest"
    if latest_dir.exists():
        shutil.rmtree(latest_dir)
    shutil.copytree(output_dir, latest_dir)


def clean_chart_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for image_path in output_dir.glob("*.png"):
        image_path.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update the investment dashboard.")
    parser.add_argument("--period", default="18mo", help="yfinance period to download, default: 18mo")
    parser.add_argument("--date", default=date.today().isoformat(), help="output date folder, default: today")
    return parser.parse_args()


def main() -> None:
    configure_fonts()
    args = parse_args()
    watchlist = read_watchlist(WATCHLIST_PATH)
    output_dir = CHARTS_DIR / args.date
    clean_chart_dir(output_dir)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    summaries = [
        summarize_stock(row, output_dir, args.period)
        for _, row in watchlist.iterrows()
    ]
    write_outputs(summaries, args.date)
    if any(item.chart_paths for item in summaries):
        copy_latest_charts(output_dir)

    print(f"Updated dashboard: {DASHBOARD_PATH}")
    print(f"Updated report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
