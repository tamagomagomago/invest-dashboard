#!/usr/bin/env python3
"""Send an optional LINE Messaging API notification for dashboard updates."""

from __future__ import annotations

import argparse
import os
import sys

import requests


LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def send_line_message(message: str) -> None:
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    to = os.getenv("LINE_TO")
    if not token or not to:
        print("LINE notification skipped: LINE_CHANNEL_ACCESS_TOKEN or LINE_TO is not set.")
        return

    response = requests.post(
        LINE_PUSH_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "to": to,
            "messages": [{"type": "text", "text": message[:5000]}],
        },
        timeout=20,
    )
    if response.status_code >= 400:
        print(
            f"LINE notification response: {response.status_code} {response.text}",
            file=sys.stderr,
        )
    response.raise_for_status()
    print("LINE notification sent.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a LINE notification.")
    parser.add_argument("--status", required=True)
    parser.add_argument("--url", default="")
    parser.add_argument("--run-url", default="")
    args = parser.parse_args()

    status_label = {
        "success": "GitHub Pages更新完了",
        "failure": "更新失敗",
        "cancelled": "更新キャンセル",
        "skipped": "更新スキップ",
    }.get(args.status, args.status)
    message = f"投資ダッシュボード: {status_label}"
    if args.url:
        message += f"\n{args.url}"
    if args.run_url:
        message += f"\nActions: {args.run_url}"

    try:
        send_line_message(message)
    except Exception as exc:
        print(f"LINE notification failed: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
