#!/usr/bin/env python3
"""
Toreta(トレタ)予約サイトの空き枠を監視し、空きが出たらスマホに通知する。
標準ライブラリのみで動作(pip install 不要)。

設定はすべて環境変数で渡す:
  TORETA_SLUG     店舗のURL名 (例: bistroshin3)            ※デフォルト bistroshin3
  TARGET_DATES    監視する日付。カンマ区切り (例: 2026-12-24,2026-12-25)  ※必須
  SEATS           人数 (例: 2)                               ※デフォルト 2
  TIME_FROM       この時刻以降の入店枠だけ対象 (例: 18:00)   ※任意
  TIME_TO         この時刻以前の入店枠だけ対象 (例: 20:00)   ※任意
  NTFY_TOPIC      ntfy.sh のトピック名(推測されにくい文字列にする)  ※通知先
  DISCORD_WEBHOOK Discord の Webhook URL                     ※任意(ntfyの代わり/併用)
  STATE_FILE      前回通知した枠を保存するファイル           ※デフォルト state.json
"""
import base64
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

BASE = "https://yoyaku.toreta.in/web/v1/web_reservations"
UA = "Mozilla/5.0 (personal availability checker)"
JST = timezone(timedelta(hours=9))


def http_get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def get_restaurant_key(slug: str) -> str:
    """店舗スラッグ(bistroshin3)から、空き枠APIで使う内部キーを取得する"""
    data = http_get_json(f"{BASE}/{slug}/contents.json")
    return data["restaurant"]["key"]


def get_month_days(key: str, year: int, month: int, seats: int):
    """その月の日別の空き枠リスト。days[0]が1日。
    null=受付前/範囲外, []=満席・休業, [..]=空きのある時間帯"""
    data = http_get_json(f"{BASE}/{key}/days.json?year={year}&month={month}&seats={seats}")
    return data["result"]["days"]


def hhmm_to_sec(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 3600 + int(m) * 60


def filter_slots(slots, time_from, time_to):
    out = []
    for s in slots or []:
        st = s["start_time"]  # 0時からの秒数
        if time_from is not None and st < time_from:
            continue
        if time_to is not None and st > time_to:
            continue
        out.append(s)
    return out


def find_available(key, dates, seats, time_from=None, time_to=None, fetch=get_month_days):
    """{'2026-12-24': ['18:00入店 20:15退店', ...]} の形で空き枠を返す"""
    result = {}
    cache = {}
    for d in dates:
        ym = (d.year, d.month)
        if ym not in cache:
            cache[ym] = fetch(key, d.year, d.month, seats)
            time.sleep(0 if fetch is not get_month_days else 1)  # サーバーに優しく
        days = cache[ym]
        slots = days[d.day - 1] if d.day - 1 < len(days) else None
        slots = filter_slots(slots, time_from, time_to)
        if slots:
            result[d.isoformat()] = [s["label"] for s in slots]
    return result


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path, state):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def new_slots(current, previous):
    """前回通知していない枠だけを抜き出す(同じ枠で何度も通知しない)"""
    diff = {}
    for d, labels in current.items():
        fresh = [l for l in labels if l not in set(previous.get(d, []))]
        if fresh:
            diff[d] = fresh
    return diff


def notify(title, body, url):
    sent = False
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=body.encode("utf-8"),
            headers={
                # HTTPヘッダーは非ASCII不可なので RFC2047 形式でタイトルを渡す
                "Title": "=?UTF-8?B?" + base64.b64encode(title.encode()).decode() + "?=",
                "Click": url,
                "Priority": "high",
                "Tags": "fork_and_knife",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=20).read()
        sent = True
    hook = os.environ.get("DISCORD_WEBHOOK")
    if hook:
        payload = json.dumps({"content": f"**{title}**\n{body}\n{url}"}).encode("utf-8")
        req = urllib.request.Request(hook, data=payload,
                                     headers={"Content-Type": "application/json", "User-Agent": UA},
                                     method="POST")
        urllib.request.urlopen(req, timeout=20).read()
        sent = True
    if not sent:
        print("[warn] 通知先(NTFY_TOPIC / DISCORD_WEBHOOK)が未設定のため、表示のみ")


def main():
    slug = os.environ.get("TORETA_SLUG", "bistroshin3")
    raw_dates = os.environ.get("TARGET_DATES", "").strip()
    if not raw_dates:
        sys.exit("TARGET_DATES を設定してください (例: 2026-12-24,2026-12-25)")
    today = datetime.now(JST).date()
    dates = [date.fromisoformat(x.strip()) for x in raw_dates.split(",") if x.strip()]
    dates = [d for d in dates if d >= today]
    if not dates:
        print("監視対象の日付がすべて過去になりました。終了します。")
        return
    seats = int(os.environ.get("SEATS", "2"))
    tf = os.environ.get("TIME_FROM")
    tt = os.environ.get("TIME_TO")
    state_path = os.environ.get("STATE_FILE", "state.json")

    key = get_restaurant_key(slug)
    current = find_available(key, dates, seats,
                             hhmm_to_sec(tf) if tf else None,
                             hhmm_to_sec(tt) if tt else None)
    previous = load_state(state_path)
    fresh = new_slots(current, previous)

    stamp = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    print(f"[{stamp}] {seats}名 対象日={','.join(d.isoformat() for d in dates)} 空き={current or 'なし'}")

    if fresh:
        lines = []
        for d, labels in sorted(fresh.items()):
            lines.append(f"{d}: " + " / ".join(l.split(" ")[0] for l in labels))
        notify(f"空きが出ました({seats}名)", "\n".join(lines),
               f"https://yoyaku.toreta.in/{slug}/#/")
        print("通知しました:\n" + "\n".join(lines))

    # 現在の空き状況を保存(埋まった枠は消えるので、再び空いたらまた通知される)
    save_state(state_path, current)


if __name__ == "__main__":
    # LOOP_COUNT 回、INTERVAL_SEC 秒おきに確認する(GitHub Actionsで実質1分間隔にするため)
    loops = int(os.environ.get("LOOP_COUNT", "1"))
    interval = int(os.environ.get("INTERVAL_SEC", "60"))
    for i in range(loops):
        try:
            main()
        except Exception as e:  # 一時的な通信エラーで全体を止めない
            print(f"[error] {e}")
        if i < loops - 1:
            time.sleep(interval)
