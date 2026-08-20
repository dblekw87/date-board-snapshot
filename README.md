# date-board-snapshot

DATE 시장 보드의 공개 스냅샷입니다. 수집기가 로컬에서 돌면서 주기적으로 `board.json`을
밀어올리고, 배포된 프론트가 백엔드에 닿지 못할 때 이 파일을 읽습니다.

- `board.json` — 보드 전체 응답. 원본 provider payload는 빠져 있습니다.
- `meta.json` — 언제 만들어졌는지.

코드는 별도 비공개 저장소에 있고, 여기에는 화면에 그려지는 데이터만 올라옵니다.
