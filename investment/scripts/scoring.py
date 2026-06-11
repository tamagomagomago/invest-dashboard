"""Scoring rules for the investment watchlist dashboard."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD


@dataclass
class ScoreResult:
    total_score: int
    signal_label: str
    trend_score: int
    breakout_score: int
    volume_score: int
    rsi_score: int
    reversal_score: int
    risk_penalty: int
    reversal_label: str
    comments: list[str]
    reasons: dict[str, list[str]]


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["MA5"] = out["Close"].rolling(5).mean()
    out["MA25"] = out["Close"].rolling(25).mean()
    out["MA75"] = out["Close"].rolling(75).mean()
    out["MA200"] = out["Close"].rolling(200).mean()
    out["RSI14"] = RSIIndicator(close=out["Close"], window=14).rsi()

    macd = MACD(close=out["Close"], window_fast=12, window_slow=26, window_sign=9)
    out["MACD"] = macd.macd()
    out["MACD_Hist"] = macd.macd_diff()

    out["Volume20"] = out["Volume"].rolling(20).mean().shift(1)
    out["Volume20"] = out["Volume20"].fillna(out["Volume"].rolling(20).mean())
    out["VolumeRatio"] = out["Volume"] / out["Volume20"].replace(0, np.nan)

    out["High52w"] = out["High"].rolling(252, min_periods=60).max()
    out["PrevHigh52w"] = out["High"].shift(1).rolling(252, min_periods=60).max()
    out["High20"] = out["High"].rolling(20, min_periods=5).max()
    out["PrevHigh20"] = out["High"].shift(1).rolling(20, min_periods=5).max()
    out["DrawdownFrom52wHigh"] = out["Close"] / out["High52w"].replace(0, np.nan) - 1
    out["Return5d"] = out["Close"].pct_change(5)
    out["Return10d"] = out["Close"].pct_change(10)
    return out


def is_bullish(row: pd.Series) -> bool:
    return pd.notna(row.get("Open")) and pd.notna(row.get("Close")) and row["Close"] > row["Open"]


def body_size(row: pd.Series) -> float:
    return abs(float(row["Close"]) - float(row["Open"]))


def candle_range(row: pd.Series) -> float:
    return max(float(row["High"]) - float(row["Low"]), 0.0)


def is_big_bearish(row: pd.Series) -> bool:
    if pd.isna(row.get("Open")) or pd.isna(row.get("Close")) or row["Close"] >= row["Open"]:
        return False
    body = body_size(row)
    open_price = float(row["Open"])
    range_size = candle_range(row)
    body_ratio = body / open_price if open_price else 0.0
    range_ratio = body / range_size if range_size else 0.0
    return body_ratio >= 0.03 or range_ratio >= 0.65


def is_small_bullish(row: pd.Series) -> bool:
    if not is_bullish(row):
        return False
    range_size = candle_range(row)
    return range_size > 0 and body_size(row) / range_size <= 0.35


def is_lower_shadow_bullish(row: pd.Series) -> bool:
    if not is_bullish(row):
        return False
    body = body_size(row)
    range_size = candle_range(row)
    lower_shadow = min(float(row["Open"]), float(row["Close"])) - float(row["Low"])
    return range_size > 0 and lower_shadow >= max(body * 1.5, range_size * 0.35)


def is_bullish_engulfing(prev: pd.Series, current: pd.Series) -> bool:
    if pd.isna(prev.get("Open")) or pd.isna(prev.get("Close")):
        return False
    if not is_bullish(current) or prev["Close"] >= prev["Open"]:
        return False
    return current["Open"] <= prev["Close"] and current["Close"] >= prev["Open"]


def rising_close(df: pd.DataFrame, days: int) -> bool:
    values = df["Close"].tail(days).dropna()
    if len(values) < days:
        return False
    return all(values.iloc[i] > values.iloc[i - 1] for i in range(1, len(values)))


def bullish_streak(df: pd.DataFrame, days: int) -> bool:
    recent = df.tail(days)
    if len(recent) < days:
        return False
    return all(is_bullish(row) for _, row in recent.iterrows())


def signal_label(total_score: int) -> str:
    if total_score >= 85:
        return "最優先候補"
    if total_score >= 75:
        return "買い候補"
    if total_score >= 65:
        return "監視上位"
    if total_score >= 50:
        return "監視継続"
    if total_score >= 35:
        return "弱い"
    return "除外候補"


def score_trend(df: pd.DataFrame) -> tuple[int, list[str]]:
    latest = df.iloc[-1]
    score = 0
    reasons: list[str] = []

    checks = [
        ("終値 > MA75", 6, latest["Close"] > latest.get("MA75")),
        ("終値 > MA200", 4, latest["Close"] > latest.get("MA200")),
        ("MA25 > MA75", 4, latest.get("MA25") > latest.get("MA75")),
        ("MA5 > MA25", 3, latest.get("MA5") > latest.get("MA25")),
    ]
    for label, points, ok in checks:
        if bool(ok):
            score += points
            reasons.append(f"{label}: +{points}")

    if len(df) >= 6 and pd.notna(latest.get("MA75")) and pd.notna(df["MA75"].iloc[-6]):
        if latest["MA75"] > df["MA75"].iloc[-6]:
            score += 3
            reasons.append("MA75が5営業日前より上向き: +3")

    return min(score, 20), reasons


def score_breakout(df: pd.DataFrame) -> tuple[int, list[str]]:
    latest = df.iloc[-1]
    score = 0
    reasons: list[str] = []

    if pd.notna(latest.get("PrevHigh52w")) and latest["High"] >= latest["PrevHigh52w"]:
        score += 10
        reasons.append("52週高値更新: +10")
    elif pd.notna(latest.get("High52w")) and latest["High52w"] > 0 and latest["Close"] >= latest["High52w"] * 0.95:
        score += 6
        reasons.append("52週高値から5%以内: +6")

    if pd.notna(latest.get("PrevHigh20")) and latest["High"] >= latest["PrevHigh20"]:
        score += 4
        reasons.append("20日高値更新: +4")
    if pd.notna(latest.get("PrevHigh20")) and latest["Close"] > latest["PrevHigh20"]:
        score += 4
        reasons.append("終値が直近20日高値を上抜け: +4")
    if pd.notna(latest.get("Return10d")) and latest["Return10d"] >= 0.10:
        score += 3
        reasons.append("直近10営業日で+10%以上: +3")

    return min(score, 20), reasons


def score_volume(df: pd.DataFrame) -> tuple[int, list[str]]:
    latest = df.iloc[-1]
    recent3 = df.tail(3)
    score = 0
    reasons: list[str] = []
    volume20 = latest.get("Volume20")

    if pd.notna(volume20) and volume20 > 0:
        ratio = latest["Volume"] / volume20
        if ratio >= 2.0:
            score += 10
            reasons.append("当日出来高が20日平均の2.0倍以上: +10")
        elif ratio >= 1.5:
            score += 7
            reasons.append("当日出来高が20日平均の1.5倍以上: +7")

        if len(df) >= 2 and is_bullish(latest) and latest["Volume"] > df["Volume"].iloc[-2]:
            score += 3
            reasons.append("陽線日の出来高増: +3")
        if latest["Close"] < latest["Open"] and latest["Volume"] < volume20:
            score += 2
            reasons.append("下落日の出来高が20日平均未満: +2")
        if len(recent3) == 3 and recent3["Volume"].mean() >= volume20:
            score += 3
            reasons.append("直近3営業日の平均出来高が20日平均以上: +3")

    return min(score, 15), reasons


def score_rsi(df: pd.DataFrame) -> tuple[int, list[str]]:
    latest = df.iloc[-1]
    rsi = latest.get("RSI14")
    if pd.isna(rsi):
        return 0, ["RSI判定不可"]

    score = 0
    reasons: list[str] = []
    if 50 <= rsi <= 65:
        score += 10
        reasons.append("RSI50-65: +10")
    elif 65 < rsi <= 70:
        score += 7
        reasons.append("RSI65-70: +7")
    elif 70 < rsi <= 80:
        score += 2
        reasons.append("RSI70-80: +2")
    elif rsi > 90:
        score -= 15
        reasons.append("RSI90超: -15")
    elif rsi > 80:
        score -= 5
        reasons.append("RSI80超: -5")

    if len(df) >= 4:
        prev = df["RSI14"].iloc[-4:-1].dropna()
        if len(prev) >= 2 and 40 <= prev.iloc[-1] < 50 and rsi > prev.iloc[-1]:
            score = max(score, 8)
            reasons.append("RSI40-50から上向き転換: +8")

    return score, reasons


def score_reversal(df: pd.DataFrame) -> tuple[int, str, list[str], dict[str, bool]]:
    recent5 = df.tail(5)
    recent3 = df.tail(3)
    latest = df.iloc[-1]
    score = 0
    reasons: list[str] = []

    near_ma = False
    latest_close = latest["Close"]
    latest_ma75 = latest.get("MA75")
    if pd.notna(latest_ma75) and latest_close < latest_ma75 * 0.9:
        reasons.append("押し目位置: 終値がMA75を10%以上下回るため0点")
    else:
        for _, row in recent5.iterrows():
            for ma_col in ["MA25", "MA75"]:
                ma_value = row.get(ma_col)
                if pd.notna(ma_value) and ma_value > 0:
                    if abs(row["Low"] - ma_value) / ma_value <= 0.05 or abs(row["Close"] - ma_value) / ma_value <= 0.05:
                        near_ma = True
                        break
            if near_ma:
                break
        if near_ma:
            score += 5
            reasons.append("押し目位置: MA25/MA75の±5%以内: +5")

    stop_score = 0
    if len(recent3) >= 3:
        lows = recent3["Low"]
        closes = recent3["Close"]
        if lows.iloc[-1] >= lows.iloc[-2] or lows.iloc[-2] >= lows.iloc[-3]:
            stop_score += 2
            reasons.append("下落停止: 安値切り下げが停止: +2")
        if closes.iloc[-1] >= closes.iloc[0] * 0.995 or closes.iloc[-1] >= closes.iloc[-2]:
            stop_score += 2
            reasons.append("下落停止: 終値が横ばいまたは切り上げ: +2")
        if not any(is_big_bearish(row) for _, row in recent3.iterrows()):
            stop_score += 1
            reasons.append("下落停止: 大陰線なし: +1")
    score += min(stop_score, 5)

    candle_score = 0
    reversal_day_pos: int | None = None
    candle_reasons: list[str] = []
    for pos in range(max(0, len(df) - 5), len(df)):
        row = df.iloc[pos]
        day_score = 0
        day_reasons: list[str] = []
        if is_small_bullish(row):
            day_score += 2
            day_reasons.append("小陽線: +2")
        if is_lower_shadow_bullish(row):
            day_score += 3
            day_reasons.append("下ヒゲ陽線: +3")
        if pos > 0 and is_bullish_engulfing(df.iloc[pos - 1], row):
            day_score += 4
            day_reasons.append("陽線包み足: +4")
        if day_score > candle_score:
            candle_score = min(day_score, 5)
            reversal_day_pos = pos
            candle_reasons = day_reasons
    if candle_score:
        score += candle_score
        reasons.append("陽線転換: " + " / ".join(candle_reasons))

    continuation_score = 0
    close_up_2 = rising_close(df, 2)
    close_up_3 = rising_close(df, 3)
    bull_2 = bullish_streak(df, 2)
    bull_3 = bullish_streak(df, 3)
    if close_up_3:
        continuation_score = max(continuation_score, 5)
        reasons.append("続伸: 直近3営業日で終値切り上げ: +5")
    elif close_up_2:
        continuation_score = max(continuation_score, 3)
        reasons.append("続伸: 直近2営業日で終値切り上げ: +3")
    if bull_3:
        continuation_score = max(continuation_score, 6)
        reasons.append("続伸: 直近3営業日で陽線継続: +6")
    elif bull_2:
        continuation_score = max(continuation_score, 3)
        reasons.append("続伸: 直近2営業日以上で陽線継続: +3")
    score += min(continuation_score, 6)

    volume_score = 0
    volume_20_or_more = False
    volume_15_or_more = False
    if reversal_day_pos is not None:
        reversal_row = df.iloc[reversal_day_pos]
        volume20 = reversal_row.get("Volume20")
        if pd.notna(volume20) and volume20 > 0 and reversal_row["Volume"] >= volume20:
            volume_score = max(volume_score, 2)
            volume_20_or_more = True
            reasons.append("出来高確認: 反転陽線日が20日平均以上: +2")

    for _, row in recent3.iterrows():
        volume20 = row.get("Volume20")
        if pd.notna(volume20) and volume20 > 0:
            if row["Volume"] >= volume20:
                volume_20_or_more = True
            if row["Volume"] >= volume20 * 1.5:
                volume_15_or_more = True
    if volume_15_or_more and (close_up_2 or bull_2):
        volume_score = max(volume_score, 4)
        reasons.append("出来高確認: 続伸日に20日平均の1.5倍以上: +4")

    bullish_recent = recent3[recent3["Close"] > recent3["Open"]]
    if len(bullish_recent) >= 2:
        volumes = bullish_recent["Volume"].tail(2)
        if volumes.iloc[-1] > volumes.iloc[0]:
            volume_score = max(volume_score, 2)
            reasons.append("出来高確認: 陽線の日に出来高増加: +2")
    score += min(volume_score, 4)

    if near_ma and close_up_3 and (bull_2 or bull_3) and volume_15_or_more:
        label = "反転初動・かなり強い"
    elif near_ma and close_up_2 and bull_2 and volume_20_or_more:
        label = "反転初動・強"
    elif score >= 16:
        label = "反転初動・候補"
    else:
        label = "反転初動・弱/未確認"

    flags = {
        "near_ma": near_ma,
        "close_up_2": close_up_2,
        "close_up_3": close_up_3,
        "bull_2": bull_2,
        "bull_3": bull_3,
        "volume_20_or_more": volume_20_or_more,
        "volume_15_or_more": volume_15_or_more,
    }
    return min(score, 25), label, reasons, flags


def score_risk(df: pd.DataFrame) -> tuple[int, list[str]]:
    latest = df.iloc[-1]
    penalty = 0
    reasons: list[str] = []

    if pd.notna(latest.get("MA75")) and latest["Close"] < latest["MA75"]:
        penalty -= 8
        reasons.append("終値 < MA75: -8")
    if pd.notna(latest.get("MA25")) and pd.notna(latest.get("MA75")) and latest["MA25"] < latest["MA75"]:
        penalty -= 6
        reasons.append("MA25 < MA75: -6")
    if is_big_bearish(latest) and pd.notna(latest.get("Volume20")) and latest["Volume"] >= latest["Volume20"]:
        penalty -= 8
        reasons.append("出来高を伴う大陰線: -8")
    if pd.notna(latest.get("DrawdownFrom52wHigh")) and latest["DrawdownFrom52wHigh"] <= -0.20:
        penalty -= 5
        reasons.append("52週高値から20%以上下落: -5")
    if pd.notna(latest.get("RSI14")) and latest["RSI14"] > 90:
        penalty -= 15
        reasons.append("RSI90超: -15")
    if pd.notna(latest.get("Return5d")) and latest["Return5d"] <= -0.15:
        penalty -= 8
        reasons.append("直近5営業日で-15%以上下落: -8")

    return max(penalty, -25), reasons


def score_stock(df: pd.DataFrame) -> ScoreResult:
    if len(df) < 80:
        return ScoreResult(
            total_score=0,
            signal_label="判定不可",
            trend_score=0,
            breakout_score=0,
            volume_score=0,
            rsi_score=0,
            reversal_score=0,
            risk_penalty=0,
            reversal_label="判定不可",
            comments=["データ不足"],
            reasons={},
        )

    trend_score, trend_reasons = score_trend(df)
    breakout_score, breakout_reasons = score_breakout(df)
    volume_score, volume_reasons = score_volume(df)
    rsi_score, rsi_reasons = score_rsi(df)
    reversal_score, reversal_label, reversal_reasons, _ = score_reversal(df)
    risk_penalty, risk_reasons = score_risk(df)

    total = trend_score + breakout_score + volume_score + rsi_score + reversal_score + risk_penalty
    total = int(min(max(total, 0), 100))

    comments: list[str] = []
    if breakout_score >= 10:
        comments.append("高値圏の強さあり")
    if trend_score >= 14:
        comments.append("上昇トレンド良好")
    if volume_score >= 7:
        comments.append("出来高増加")
    if reversal_label in {"反転初動・強", "反転初動・かなり強い"}:
        comments.append(reversal_label)
    if risk_penalty <= -10:
        comments.append("リスク減点大きめ")
    if not comments:
        comments.append("監視継続。根拠の積み上がり待ち")

    return ScoreResult(
        total_score=total,
        signal_label=signal_label(total),
        trend_score=trend_score,
        breakout_score=breakout_score,
        volume_score=volume_score,
        rsi_score=rsi_score,
        reversal_score=reversal_score,
        risk_penalty=risk_penalty,
        reversal_label=reversal_label,
        comments=comments,
        reasons={
            "trend": trend_reasons,
            "breakout": breakout_reasons,
            "volume": volume_reasons,
            "rsi": rsi_reasons,
            "reversal": reversal_reasons,
            "risk": risk_reasons,
        },
    )
