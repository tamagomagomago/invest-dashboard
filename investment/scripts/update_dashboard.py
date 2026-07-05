#!/usr/bin/env python3
"""Fetch prices, score watchlist stocks, and render a lightweight investment dashboard.

This version intentionally does not generate PNG charts or per-symbol CSV files.
It keeps GitHub Pages artifacts small: dashboard HTML, report markdown, and latest score JSON only.
"""

from __future__ import annotations

import argparse
import html
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

from scoring import ScoreResult, add_indicators, score_stock


ROOT_DIR = Path(__file__).resolve().parents[1]
WATCHLIST_PATH = ROOT_DIR / "watchlist.csv"
DASHBOARD_PATH = ROOT_DIR / "dashboard.html"
INDEX_PATH = ROOT_DIR / "index.html"
REPORT_PATH = ROOT_DIR / "report.md"
DATA_DIR = ROOT_DIR / "data"
REPORTS_DIR = ROOT_DIR / "reports"
JST = ZoneInfo("Asia/Tokyo")
MARKET_SYMBOLS = [
    ("日経平均", "^N225"),
    ("TOPIX ETF", "1306.T"),
    ("グロース250 ETF", "2516.T"),
    ("ドル円", "JPY=X"),
    ("NASDAQ", "^IXIC"),
    ("S&P500", "^GSPC"),
    ("SOX", "^SOX"),
]


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
    return1d: float | None
    return5d: float | None
    score: ScoreResult
    error: str | None = None


@dataclass
class MarketMove:
    name: str
    symbol: str
    latest_date: str | None
    close: float | None
    return1d: float | None
    return5d: float | None
    return20d: float | None
    error: str | None = None


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


def empty_score(label: str = "判定不可") -> ScoreResult:
    return ScoreResult(
        total_score=0,
        signal_label=label,
        trend_score=0,
        breakout_score=0,
        volume_score=0,
        rsi_score=0,
        reversal_score=0,
        wave_score=0,
        wave_label=label,
        risk_penalty=0,
        reversal_label=label,
        comments=["取得または判定に失敗"],
        reasons={},
    )


def summarize_market_symbol(name: str, symbol: str) -> MarketMove:
    try:
        df = fetch_prices(symbol, "3mo")
        if len(df) < 6:
            raise ValueError("market data is too short")
        latest = df.iloc[-1]
        return MarketMove(
            name=name,
            symbol=symbol,
            latest_date=latest.name.strftime("%Y-%m-%d"),
            close=float(latest["Close"]),
            return1d=float(df["Close"].pct_change(1).iloc[-1]) if len(df) >= 2 else None,
            return5d=float(df["Close"].pct_change(5).iloc[-1]) if len(df) >= 6 else None,
            return20d=float(df["Close"].pct_change(20).iloc[-1]) if len(df) >= 21 else None,
        )
    except Exception as exc:
        return MarketMove(name, symbol, None, None, None, None, None, str(exc))


def summarize_market() -> list[MarketMove]:
    return [summarize_market_symbol(name, symbol) for name, symbol in MARKET_SYMBOLS]


def summarize_stock(row: pd.Series, period: str) -> StockSummary:
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
        score = score_stock(df)
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
            return1d=float(latest["Return1d"]) if pd.notna(latest.get("Return1d")) else None,
            return5d=float(latest["Return5d"]) if pd.notna(latest.get("Return5d")) else None,
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
            return1d=None,
            return5d=None,
            score=empty_score(),
            error=str(exc),
        )


def score_class(item: StockSummary) -> str:
    if item.error:
        return "muted"
    score = item.score.total_score
    if score >= 75:
        return "strong"
    if score >= 50:
        return "watch"
    if score >= 35:
        return "weak"
    return "exclude"


def move_class(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "flat"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def theme_strength(summaries: list[StockSummary]) -> list[dict[str, object]]:
    buckets: dict[str, list[StockSummary]] = {}
    for item in summaries:
        if item.error:
            continue
        keys = [part.strip() for part in item.list_name.split("|") if part.strip()]
        if item.memo:
            keys.append(item.memo.strip())
        for key in keys:
            buckets.setdefault(key, []).append(item)

    rows = []
    for name, items in buckets.items():
        if len(items) < 2:
            continue
        returns = [item.return5d for item in items if item.return5d is not None and not pd.isna(item.return5d)]
        volumes = [item.volume_ratio for item in items if item.volume_ratio is not None and not pd.isna(item.volume_ratio)]
        rows.append(
            {
                "name": name,
                "count": len(items),
                "avg_return5d": float(np.nanmean(returns)) if returns else None,
                "avg_volume": float(np.nanmean(volumes)) if volumes else None,
                "avg_score": float(np.nanmean([item.score.total_score for item in items])),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["avg_return5d"] if row["avg_return5d"] is not None else -999,
            row["avg_score"],
        ),
        reverse=True,
    )


def render_market_overview(market_moves: list[MarketMove], summaries: list[StockSummary]) -> str:
    cards = []
    for move in market_moves:
        if move.error:
            cards.append(f"<div class='market-card muted'><strong>{html.escape(move.name)}</strong><em>取得不可</em></div>")
            continue
        cls = "up" if (move.return1d or 0) >= 0 else "down"
        cards.append(
            f"""
            <div class="market-card {cls}">
              <strong>{html.escape(move.name)}</strong>
              <span>{html.escape(move.latest_date or '-')} / {html.escape(move.symbol)}</span>
              <em>{fmt_number(move.close, 2)}</em>
              <small>1日 {fmt_percent(move.return1d)} / 5日 {fmt_percent(move.return5d)} / 20日 {fmt_percent(move.return20d)}</small>
            </div>
            """
        )

    themes = theme_strength(summaries)[:8]
    theme_rows = "".join(
        f"<li><strong>{html.escape(str(theme['name']))}</strong><span>{int(theme['count'])}銘柄 / 5日 {fmt_percent(theme['avg_return5d'])} / 出来高 {fmt_number(theme['avg_volume'], 2)}x / 平均点 {fmt_number(theme['avg_score'], 1)}</span></li>"
        for theme in themes
    ) or "<li>テーマ集計なし</li>"

    early_items = sorted(
        [item for item in summaries if not item.error],
        key=lambda item: (item.score.wave_score, item.score.reversal_score, item.score.total_score),
        reverse=True,
    )[:8]
    early_rows = "".join(
        f"<li><strong>{html.escape(item.code)} {html.escape(item.name)}</strong><span>初動 {item.score.wave_score}/10 / 反転 {item.score.reversal_score}/25 / 総合 {item.score.total_score}</span></li>"
        for item in early_items
    ) or "<li>候補なし</li>"

    return f"""
    <section class="market-overview">
      <h2>今日の相場メモ</h2>
      <p>軽量版：チャート画像と銘柄別CSVは生成していません。</p>
      <div class="market-grid">{''.join(cards)}</div>
      <div class="overview-columns">
        <div><h3>最近強いテーマ</h3><ul>{theme_rows}</ul></div>
        <div><h3>上昇初動・第3波候補</h3><ul>{early_rows}</ul></div>
      </div>
    </section>
    """


def render_dashboard(summaries: list[StockSummary], market_moves: list[MarketMove], generated_on: str) -> str:
    sorted_items = sorted(summaries, key=lambda item: item.score.total_score, reverse=True)
    list_names: list[str] = []
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
        score = item.score
        comments = " / ".join(score.comments)
        error = f"<p class='error'>取得エラー: {html.escape(item.error)}</p>" if item.error else ""
        rows.append(
            f"""
            <tr class="stock {score_class(item)}" data-list="{html.escape(item.list_name)}" data-total="{score.total_score}" data-reversal="{score.reversal_score}" data-wave="{score.wave_score}" data-breakout="{score.breakout_score}" data-volume="{score.volume_score}" data-risk="{score.risk_penalty}">
              <td><strong>{html.escape(item.code)} {html.escape(item.name)}</strong><br><span>{html.escape(item.symbol)} / {html.escape(item.list_name)}{(' / ' + html.escape(item.memo)) if item.memo else ''}</span>{error}</td>
              <td class="score">{score.total_score}</td>
              <td>{html.escape(score.signal_label)}<br><span>{html.escape(score.reversal_label)} / {html.escape(score.wave_label)}</span></td>
              <td>{fmt_number(item.close, 0)}<br><span>{html.escape(item.latest_date or '-')}</span></td>
              <td class="{move_class(item.return1d)}">{fmt_percent(item.return1d)}<br><span>5日 {fmt_percent(item.return5d)}</span></td>
              <td>{fmt_number(item.rsi, 1)}<br><span>出来高 {fmt_number(item.volume_ratio, 2)}x</span></td>
              <td>{score.trend_score}/{score.breakout_score}/{score.volume_score}/{score.rsi_score}<br><span>反転 {score.reversal_score} / 初動 {score.wave_score} / リスク {score.risk_penalty}</span></td>
              <td>{html.escape(comments)}</td>
            </tr>
            """
        )

    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Investment Watchlist Dashboard</title>
  <style>
    :root {{ --bg:#f6f8fa; --panel:#fff; --text:#17202a; --muted:#65717f; --line:#d8dee4; --strong:#0b7a53; --watch:#b26b00; --weak:#9c2f2f; --accent:#214f7a; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; line-height:1.5; }}
    header, .toolbar, .market-overview {{ padding:16px clamp(12px,4vw,40px); background:var(--panel); border-bottom:1px solid var(--line); }}
    h1 {{ margin:0; font-size:26px; }}
    h2 {{ margin:0 0 6px; font-size:18px; }}
    h3 {{ margin:0; font-size:15px; }}
    p, span, small {{ color:var(--muted); }}
    .toolbar {{ position:sticky; top:0; display:flex; gap:8px; flex-wrap:wrap; z-index:10; }}
    button {{ border:1px solid var(--line); background:#fff; border-radius:8px; padding:7px 10px; font-weight:700; cursor:pointer; }}
    button.active {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
    .market-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:8px; margin:10px 0; }}
    .market-card {{ border:1px solid var(--line); border-radius:8px; padding:10px; background:#fff; }}
    .market-card strong, .market-card span, .market-card em, .market-card small {{ display:block; overflow-wrap:anywhere; }}
    .market-card em {{ font-style:normal; font-weight:800; margin:3px 0; }}
    .up, .market-card.up em {{ color:var(--strong); }}
    .down, .market-card.down em {{ color:var(--weak); }}
    .overview-columns {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:12px; }}
    .overview-columns > div {{ border:1px solid var(--line); border-radius:8px; padding:12px; }}
    .overview-columns ul {{ list-style:none; padding:0; margin:8px 0 0; }}
    .overview-columns li {{ display:flex; justify-content:space-between; gap:10px; border-top:1px solid #edf0f2; padding:7px 0; }}
    main {{ padding:16px clamp(12px,4vw,40px) 40px; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); font-size:13px; }}
    th, td {{ border-bottom:1px solid var(--line); padding:9px; text-align:left; vertical-align:top; }}
    th {{ position:sticky; top:55px; background:#f8fafc; z-index:5; }}
    tr.strong td:first-child {{ border-left:5px solid var(--strong); }}
    tr.watch td:first-child {{ border-left:5px solid var(--watch); }}
    tr.weak td:first-child {{ border-left:5px solid var(--weak); }}
    tr.exclude td:first-child, tr.muted td:first-child {{ border-left:5px solid var(--muted); }}
    td.score {{ font-size:22px; font-weight:800; text-align:center; }}
    .error {{ margin:4px 0 0; color:var(--weak); font-size:12px; }}
    @media (max-width: 800px) {{ table {{ display:block; overflow-x:auto; white-space:nowrap; }} .overview-columns li {{ display:block; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Investment Watchlist Dashboard</h1>
    <p>Generated: {html.escape(generated_on)} / 軽量版：画像・銘柄別CSVなし / スコアは売買推奨ではなく監視優先度です。</p>
  </header>
  {render_market_overview(market_moves, summaries)}
  <nav class="toolbar" aria-label="Dashboard controls">
    {list_buttons}
    <button type="button" class="sort-tab active" data-sort="total" data-order="desc">総合</button>
    <button type="button" class="sort-tab" data-sort="reversal" data-order="desc">反転</button>
    <button type="button" class="sort-tab" data-sort="wave" data-order="desc">初動</button>
    <button type="button" class="sort-tab" data-sort="breakout" data-order="desc">新高値</button>
    <button type="button" class="sort-tab" data-sort="volume" data-order="desc">出来高</button>
    <button type="button" class="sort-tab" data-sort="risk" data-order="asc">リスク</button>
  </nav>
  <main>
    <table>
      <thead><tr><th>銘柄</th><th>点</th><th>判定</th><th>終値</th><th>騰落</th><th>RSI/出来高</th><th>内訳</th><th>コメント</th></tr></thead>
      <tbody id="stock-list">{''.join(rows)}</tbody>
    </table>
  </main>
  <script>
    document.querySelectorAll(".list-tab").forEach((button) => {{
      button.addEventListener("click", () => {{
        const listName = button.dataset.list;
        document.querySelectorAll(".stock").forEach((row) => {{
          const lists = (row.dataset.list || "").split("|");
          row.hidden = listName !== "all" && !lists.includes(listName);
        }});
        document.querySelectorAll(".list-tab").forEach((tab) => tab.classList.toggle("active", tab === button));
      }});
    }});
    document.querySelectorAll(".sort-tab").forEach((button) => {{
      button.addEventListener("click", () => {{
        const key = button.dataset.sort;
        const order = button.dataset.order === "asc" ? 1 : -1;
        const list = document.getElementById("stock-list");
        const rows = Array.from(list.querySelectorAll(".stock"));
        rows.sort((a, b) => (Number(a.dataset[key] || 0) - Number(b.dataset[key] || 0)) * order);
        rows.forEach((row) => list.appendChild(row));
        document.querySelectorAll(".sort-tab").forEach((tab) => tab.classList.toggle("active", tab === button));
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
        if key == "wave":
            return f"{score.wave_score}/10点 / {score.wave_label}"
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


def market_report_lines(market_moves: list[MarketMove]) -> str:
    lines = []
    for move in market_moves:
        if move.error:
            lines.append(f"- {move.name} ({move.symbol}): 取得不可")
        else:
            lines.append(
                f"- {move.name} ({move.symbol}): {fmt_number(move.close, 2)} / "
                f"1日 {fmt_percent(move.return1d)} / 5日 {fmt_percent(move.return5d)} / 20日 {fmt_percent(move.return20d)}"
            )
    return "\n".join(lines) if lines else "- なし"


def theme_report_lines(summaries: list[StockSummary]) -> str:
    themes = theme_strength(summaries)[:10]
    if not themes:
        return "- なし"
    return "\n".join(
        f"- {theme['name']}: {int(theme['count'])}銘柄 / 5日 {fmt_percent(theme['avg_return5d'])} / "
        f"出来高 {fmt_number(theme['avg_volume'], 2)}x / 平均点 {fmt_number(theme['avg_score'], 1)}"
        for theme in themes
    )


def render_report(summaries: list[StockSummary], market_moves: list[MarketMove], generated_on: str) -> str:
    ok_items = [item for item in summaries if not item.error]
    errors = [item for item in summaries if item.error]
    total_ranked = sorted(ok_items, key=lambda item: item.score.total_score, reverse=True)
    reversal_ranked = sorted(ok_items, key=lambda item: item.score.reversal_score, reverse=True)
    wave_ranked = sorted(ok_items, key=lambda item: item.score.wave_score, reverse=True)
    breakout_ranked = sorted(ok_items, key=lambda item: item.score.breakout_score, reverse=True)
    volume_ranked = sorted(ok_items, key=lambda item: item.score.volume_score, reverse=True)
    risk_ranked = sorted(ok_items, key=lambda item: item.score.risk_penalty)
    exclude_items = [item for item in total_ranked if item.score.signal_label == "除外候補"]
    error_lines = "\n".join(f"- {item.code} {item.name}: {item.error}" for item in errors) if errors else "- なし"

    return f"""# 投資ダッシュボード レポート

Generated: {generated_on}

軽量版：チャート画像と銘柄別CSVは生成していません。
このスコアは売買推奨ではなく、監視優先度を決めるためのスコアです。

## 今日の相場メモ

{market_report_lines(market_moves)}

## 最近強いテーマ

{theme_report_lines(summaries)}

## 総合スコアランキング

{ranking_lines(total_ranked, "total")}

## 反転初動スコアランキング

{ranking_lines(reversal_ranked, "reversal")}

## 上昇初動・第3波候補ランキング

{ranking_lines(wave_ranked, "wave")}

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


def write_outputs(summaries: list[StockSummary], market_moves: list[MarketMove], output_date: str) -> None:
    generated_on = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    dashboard_html = render_dashboard(summaries, market_moves, generated_on)
    DASHBOARD_PATH.write_text(dashboard_html, encoding="utf-8")
    INDEX_PATH.write_text(dashboard_html, encoding="utf-8")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    daily_report_dir = REPORTS_DIR / output_date
    daily_report_dir.mkdir(parents=True, exist_ok=True)
    report = render_report(summaries, market_moves, generated_on)
    REPORT_PATH.write_text(report, encoding="utf-8")
    (REPORTS_DIR / "report.md").write_text(report, encoding="utf-8")
    (daily_report_dir / "report.md").write_text(report, encoding="utf-8")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
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
                "wave_score": item.score.wave_score,
                "wave_label": item.score.wave_label,
                "risk_penalty": item.score.risk_penalty,
                "return1d": item.return1d,
                "return5d": item.return5d,
                "volume_ratio": item.volume_ratio,
                "comments": item.score.comments,
                "reasons": item.score.reasons,
                "error": item.error,
            }
        )
    (DATA_DIR / "latest_scores.json").write_text(
        json.dumps(score_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update the lightweight investment dashboard.")
    parser.add_argument("--period", default="18mo", help="yfinance period to download, default: 18mo")
    parser.add_argument("--date", default=date.today().isoformat(), help="output date folder, default: today")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    watchlist = read_watchlist(WATCHLIST_PATH)
    summaries = [summarize_stock(row, args.period) for _, row in watchlist.iterrows()]
    market_moves = summarize_market()
    write_outputs(summaries, market_moves, args.date)
    print(f"Updated lightweight dashboard: {DASHBOARD_PATH}")
    print(f"Updated lightweight report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
