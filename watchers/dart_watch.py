#!/usr/bin/env python3
"""DART 호재 공시 감시기.

2분마다 DART 당일 공시 목록을 읽어 호재성 공시(자사주 소각·무상증자·공급계약 등)가
새로 뜨면 macOS 알림을 띄우고 briefings/dart-alerts-YYYY-MM-DD.md 에 기록한다.
Claude 호출 없음. 실행: python3 scripts/dart_watch.py  (Ctrl+C 로 종료)
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
STATE = os.path.join(ROOT, "scripts", ".dart_seen.json")
INTERVAL = int(os.environ.get("DART_INTERVAL", "120"))  # 초
HEADERS = {"User-Agent": "Mozilla/5.0"}

# 호재 키워드 (제목 기준). 정정·해지는 제외.
GOOD = [
    "주식소각결정", "무상증자결정", "자기주식취득결정", "자기주식취득신탁계약체결",
    "단일판매ㆍ공급계약체결", "단일판매·공급계약체결", "단일판매 공급계약체결",
    "임상시험계획승인", "임상시험결과", "품목허가", "특허권취득", "신규시설투자",
    "타법인주식및출자증권취득결정", "매매거래정지및정지해제", "합병결정", "분할결정",
    "무상감자", "현금ㆍ현물배당결정", "주식배당결정", "최대주주변경",
]
BAD_HINT = ["해지", "취소", "철회", "미확정", "불성실", "조회공시요구", "유상증자결정", "전환사채권발행결정",
            "신주인수권부사채권발행결정", "[기재정정]", "[첨부정정]", "[첨부추가]", "담보제공"]
MARKET_OK = {"유", "코"}  # 유가증권·코스닥만


def fetch(page: int, day: str) -> str:
    url = (f"https://dart.fss.or.kr/dsac001/mainAll.do?selectDate={day}"
           f"&sort=&series=&mdayCnt=0&currentPage={page}")
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")


def parse(html: str):
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    out = []
    for r in rows:
        m_time = re.search(r"<td>\s*(\d{2}:\d{2})\s*</td>", r)
        m_mkt = re.search(r'class="tagCom_\w+"[^>]*>(.)</span>', r)
        m_co = re.search(r"title=\"([^\"]+) 기업개황 새창\"", r)
        m_rep = re.search(r'id="r_(\d+)"[^>]*title="([^"]+) 공시뷰어 새창"\s*>(.*?)</a>', r, re.S)
        if not (m_time and m_co and m_rep):
            continue
        title = re.sub(r"<[^>]+>", "", m_rep.group(3))
        title = re.sub(r"\s+", " ", title).strip()
        out.append({
            "time": m_time.group(1),
            "market": m_mkt.group(1) if m_mkt else "?",
            "company": m_co.group(1).strip(),
            "rcp": m_rep.group(1),
            "title": title,
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={m_rep.group(1)}",
        })
    return out


def is_good(item) -> bool:
    if item["market"] not in MARKET_OK:
        return False
    t = item["title"]
    if any(b in t for b in BAD_HINT):
        return False
    return any(g in t for g in GOOD)


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

def load_seen():
    try:
        with open(STATE, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen)[-5000:], f)


def log(item, day):
    path = os.path.join(ROOT, "briefings", f"dart-alerts-{day[:4]}-{day[4:6]}-{day[6:]}.md")
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write(f"# {day[:4]}-{day[4:6]}-{day[6:]} DART 호재 공시 알림\n\n")
        f.write(f"- {item['time']} [{item['market']}] **{item['company']}** · {item['title']} · {item['url']}\n")


def scan(day: str, seen: set, quiet: bool):
    found = []
    for page in range(1, 12):
        try:
            html = fetch(page, day)
        except Exception as e:
            print(f"[{dt.datetime.now():%H:%M}] fetch err p{page}: {e}", flush=True)
            break
        items = parse(html)
        if not items:
            break
        found.extend(items)
        if len(items) < 100:
            break
    new_good = [i for i in found if i["rcp"] not in seen and is_good(i)]
    for i in found:
        seen.add(i["rcp"])
    for i in new_good:
        log(i, day)
        if not quiet:
            notify(f"DART {i['time']} {i['company']}", i["title"])
        print(f"[{dt.datetime.now():%H:%M}] {i['time']} [{i['market']}] {i['company']} · {i['title']}", flush=True)
    return len(found), len(new_good)


def main():
    seen = load_seen()
    first = True
    print(f"DART watch start, interval {INTERVAL}s, state {STATE}", flush=True)
    while True:
        day = dt.datetime.now().strftime("%Y%m%d")
        total, n = scan(day, seen, quiet=first and "--alert-existing" not in sys.argv)
        save_seen(seen)
        if first:
            print(f"[{dt.datetime.now():%H:%M}] 초기 스캔 {total}건, 호재 {n}건 (기존분은 알림 생략)", flush=True)
            first = False
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
