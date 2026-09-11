# TodayStock 감시기 (Claude 호출 없음)

main 브랜치는 수집기가 10분마다 강제로 덮어쓰므로, 이 파일들은 `watchers` 브랜치에만 둡니다.

| 파일 | 주기 | 하는 일 |
|---|---|---|
| `dart_watch.py` | 2분 | DART 당일 공시 중 호재(주식소각·무상증자·공급계약·자사주취득·합병 등)가 새로 뜨면 알림 |
| `market_watch.py` | 3분, 평일 08~20시 | 상승률 상위 200종목 중 +15% 첫 돌파 / 3분 새 +5%p 급등 / +7%↑ 종목의 당일 호재 기사(거래대금 무관) 알림 |

알림: 환경변수 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 가 있으면 텔레그램, 없으면 macOS 알림 또는 윈도우 토스트.
기록: 스크립트 상위 폴더의 `briefings/dart-alerts-YYYY-MM-DD.md`, `briefings/market-alerts-YYYY-MM-DD.md`.
실행: `python dart_watch.py`, `python market_watch.py` (표준 라이브러리만 사용, 추가 설치 없음).

받는 법: `git fetch origin watchers && git checkout watchers` 또는
`git clone -b watchers --single-branch git@github.com:dblekw87/date-board-snapshot.git`
