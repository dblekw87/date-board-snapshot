#!/usr/bin/env python3
"""장중 급등·신규 재료 감시기 (Claude 호출 없음).

3분마다:
 1) 코스피·코스닥 상승률 상위 각 100종목을 읽어
    - 처음 +15%를 넘긴 종목 (상한가 잠기기 전 알림)
    - 직전 스캔 대비 +5%p 이상 튄 종목 (급등 시작 알림)
 2) 당일 +7% 이상인 종목 전부의 종목 뉴스를 조회해
    - 당일 기사 제목에 호재 키워드 + 회사명이 있고 처음 보는 기사면 알림
    (거래대금 제한 없음 — 에스투더블유 유형)
알림은 macOS 알림 + briefings/market-alerts-YYYY-MM-DD.md.
실행: python3 scripts/market_watch.py
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "scripts", ".market_seen.json")
INTERVAL = int(os.environ.get("MARKET_INTERVAL", "180"))
H = {"User-Agent": "Mozilla/5.0"}
SURGE_LEVEL = 15.0      # 이 등락률을 처음 넘기면 알림
JUMP_STEP = 5.0         # 한 스캔 사이 +5%p 이상이면 알림
NEWS_MIN_RATE = 7.0     # 이 등락률 이상인 종목만 뉴스 조회
KW = ["합류", "선정", "수주", "계약", "승인", "허가", "독점", "공급", "MOU", "협력", "투자유치",
      "인수", "특허", "양산", "체결", "확보", "출시", "파트너", "공동개발", "납품"]
GENERIC = ["코스닥", "코스피", "거래상위", "시황", "마감", "이 시각", "장중", "급등주", "특징주 종합", "테마", "ETF"]
EXCL = ["ETF", "ETN", "KODEX", "TIGER", "KBSTAR", "ACE ", "SOL ", "HANARO", "PLUS ", "RISE ", "스팩", "우B", "우C"]


def get(url, to=15):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=to))


def notify(title, body):
    """텔레그램(TELEGRAM_BOT_TOKEN·TELEGRAM_CHAT_ID 환경변수)이 있으면 텔레그램, 없으면 macOS 알림."""
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if tok and chat:
        try:
            import urllib.parse
            data = urllib.parse.urlencode({"chat_id": chat, "text": title + "\n" + body}).encode()
            urllib.request.urlopen(urllib.request.Request(
                f"https://api.telegram.org/bot{tok}/sendMessage", data=data), timeout=10)
            return
        except Exception as e:
            print(f"telegram err: {e}", flush=True)
    if sys.platform == "darwin":
        s = f'display notification {json.dumps(body)} with title {json.dumps(title)} sound name "Glass"'
        subprocess.run(["osascript", "-e", s], check=False)
    elif sys.platform == "win32":
        try:
            ps = f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; $t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); $x=$t.GetElementsByTagName('text'); $x.Item(0).AppendChild($t.CreateTextNode({json.dumps(title)})) | Out-Null; $x.Item(1).AppendChild($t.CreateTextNode({json.dumps(body)})) | Out-Null; [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('TodayStock').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False, capture_output=True)
        except Exception:
            pass

def log(day, line):
    p = os.path.join(ROOT, "briefings", f"market-alerts-{day}.md")
    new = not os.path.exists(p)
    with open(p, "a", encoding="utf-8") as f:
        if new:
            f.write(f"# {day} 장중 급등·신규 재료 알림\n\n")
        f.write(line + "\n")


def load():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def save(st):
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)


def num(s):
    try:
        return float(str(s).replace(",", ""))
    except Exception:
        return 0.0


def movers():
    out = []
    for mk in ("KOSPI", "KOSDAQ"):
        try:
            d = get(f"https://m.stock.naver.com/api/stocks/up/{mk}?page=1&pageSize=100")
        except Exception as e:
            print(f"[{dt.datetime.now():%H:%M}] up list err {mk}: {e}", flush=True)
            continue
        for s in d.get("stocks", []):
            name = s.get("stockName", "")
            if any(x in name for x in EXCL) or name.endswith("우"):
                continue
            out.append({
                "code": s["itemCode"], "name": name, "rate": num(s.get("fluctuationsRatio")),
                "price": s.get("closePrice"), "value": num(s.get("accumulatedTradingValue")) / 100,  # 억
                "mk": mk,
            })
    return out


def news_hits(code, name, today):
    try:
        n = get(f"https://m.stock.naver.com/api/news/stock/{code}?pageSize=5")
    except Exception:
        return []
    hits = []
    for g in n:
        for it in g.get("items", []):
            t = it.get("title", "")
            d = it.get("datetime", "")
            if not d.startswith(today):
                continue
            # 종목 뉴스 피드라 회사명 검사는 생략(영문 약칭 기사 대응), 시황성 제목만 제외
            if any(g in t for g in GENERIC):
                continue
            if any(k in t for k in KW):
                hits.append({"id": it.get("articleId") or (d + t), "time": d[8:10] + ":" + d[10:12],
                             "title": t, "office": it.get("officeName", "")})
    return hits


def scan(st, first):
    now = dt.datetime.now()
    today = now.strftime("%Y%m%d")
    day = now.strftime("%Y-%m-%d")
    if st.get("day") != day:
        st.clear()
        st["day"] = day
        st["rate"], st["surged"], st["news"] = {}, [], []
    ms = movers()
    alerts = 0
    for m in ms:
        c, r = m["code"], m["rate"]
        prev = st["rate"].get(c)
        st["rate"][c] = r
        if first:
            continue
        tag = None
        if r >= SURGE_LEVEL and c not in st["surged"]:
            st["surged"].append(c)
            tag = f"+{r:.1f}% 돌파 (상한가까지 {30 - r:.1f}%p)"
        elif prev is not None and r - prev >= JUMP_STEP:
            tag = f"급등 {prev:+.1f}% → {r:+.1f}%"
        if tag:
            line = f"- {now:%H:%M} [{m['mk']}] **{m['name']}**({c}) {tag} · {m['price']}원 · 거래대금 {m['value']:.0f}억"
            log(day, line)
            notify(f"급등 {m['name']}", tag + f" · 거래대금 {m['value']:.0f}억")
            print(line, flush=True)
            alerts += 1
    # 뉴스: +7% 이상 전부 (거래대금 무관)
    for m in ms:
        if m["rate"] < NEWS_MIN_RATE:
            continue
        for h in news_hits(m["code"], m["name"], today):
            key = f"{m['code']}:{h['id']}"
            if key in st["news"]:
                continue
            st["news"].append(key)
            if first:
                continue
            line = (f"- {now:%H:%M} [{m['mk']}] **{m['name']}**({m['code']}) 재료 {h['time']} {h['office']} · "
                    f"{h['title']} · 현재 {m['rate']:+.1f}% · 거래대금 {m['value']:.0f}억")
            log(day, line)
            notify(f"재료 {m['name']} {m['rate']:+.1f}%", h["title"])
            print(line, flush=True)
            alerts += 1
    return len(ms), alerts


def main():
    st = load()
    first = True
    print(f"market watch start, interval {INTERVAL}s", flush=True)
    while True:
        h = dt.datetime.now().hour
        if 8 <= h < 20 and dt.datetime.now().weekday() < 5:
            try:
                n, a = scan(st, first)
                save(st)
                if first:
                    print(f"[{dt.datetime.now():%H:%M}] 초기 스캔 {n}종목 (기존분 알림 생략)", flush=True)
                first = False
            except Exception as e:
                print(f"[{dt.datetime.now():%H:%M}] scan err: {e}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
