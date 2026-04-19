# 증권사 리포트 데일리 봇

컴퓨터를 켜두지 않아도 돌아가게 만들기 위해, 이 프로젝트는 `GitHub Actions + GitHub 저장소 + GitHub Pages + Telegram Bot` 조합을 기본 구조로 잡았습니다.

## 이 프로젝트가 하는 일

- 네이버 금융 리서치와 일부 증권사 공식 리서치 페이지를 함께 수집합니다.
- 날짜별로 `storage/archive/YYYY-MM-DD/` 아래에 저장합니다.
- 리포트별 메타데이터, 링크, 짧은 요약, 필독 점수를 만듭니다.
- 꼭 읽을 리포트를 자동 선별해서 텔레그램으로 보냅니다.
- 같은 데이터를 `docs/`에도 생성해서 GitHub Pages로 웹에서 다시 볼 수 있게 합니다.

중요: 저작권과 저장소 용량을 고려해서 원문 PDF나 본문 전체를 저장하지 않고, 메타데이터와 짧은 요약 중심으로 보관합니다.

## 현재 수집 소스

- `네이버 금융 리서치`: 기본 수집원입니다.
- `미래에셋증권 공식 리서치`: 공개 목록과 상세 페이지를 직접 수집합니다.
- `한국투자증권 공식 리서치`: 공개 상세 페이지를 직접 수집합니다.

참고:
- 한국투자증권은 현재 공개 PDF 원문 링크가 로그인 체크 뒤에 열리는 구조라서, 상세 페이지 본문 중심으로 수집합니다.
- 공식 소스와 네이버에서 같은 리포트가 겹치면 공식 소스를 우선 보관합니다.

## 권장 운영 구조

1. GitHub 저장소에 이 프로젝트를 올립니다.
2. Telegram Bot 토큰과 Chat ID를 GitHub Secrets에 넣습니다.
3. GitHub Actions가 평일 저녁 정해진 시각에 자동 실행됩니다.
4. 결과는 저장소에 커밋되고, 텔레그램으로 요약이 발송됩니다.
5. GitHub Pages를 켜면 웹 대시보드에서도 날짜별로 탐색할 수 있습니다.

기본 스케줄은 `평일 18:10 KST`입니다.
`.github/workflows/daily-report-digest.yml`의 cron 값을 바꾸면 원하는 시각으로 조정할 수 있습니다.

## 폴더 구조

```text
.
├─ .github/workflows/daily-report-digest.yml
├─ .env.example
├─ docs/
│  ├─ GITHUB_UPLOAD_CHECKLIST.md
│  ├─ index.html
│  └─ data/
├─ scripts/
│  └─ get_telegram_chat_id.py
├─ src/report_collector/
│  ├─ config.py
│  ├─ digest.py
│  ├─ main.py
│  ├─ models.py
│  ├─ storage.py
│  ├─ telegram_bot.py
│  └─ sources/
│     ├─ common.py
│     ├─ korea_investment.py
│     ├─ mirae_asset.py
│     └─ naver_research.py
├─ storage/archive/
├─ requirements.txt
└─ run_daily.py
```

## 로컬 실행

```bash
python -m pip install -r requirements.txt
python run_daily.py --skip-telegram
```

특정 날짜를 다시 생성하려면:

```bash
python run_daily.py --date 2026-04-16 --skip-telegram
```

로컬 환경 변수 예시는 `.env.example`에 정리해두었습니다.

## GitHub 업로드용 정리

빠르게 올릴 때는 아래 순서만 따라가면 됩니다.

```bash
git init
git branch -M main
git add .
git commit -m "feat: bootstrap broker report collector"
git remote add origin https://github.com/<your-id>/<repo-name>.git
git push -u origin main
```

업로드 후 체크리스트는 [docs/GITHUB_UPLOAD_CHECKLIST.md](docs/GITHUB_UPLOAD_CHECKLIST.md)에 정리해두었습니다.

## GitHub Secrets

저장소의 `Settings > Secrets and variables > Actions`에 아래 값을 추가하세요.

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

텔레그램 봇 준비 순서:

1. 텔레그램에서 `@BotFather`로 새 봇을 만듭니다.
2. 발급된 토큰을 `TELEGRAM_BOT_TOKEN`에 넣습니다.
3. 봇과 1:1 대화 또는 받을 그룹에 봇을 초대합니다.
4. 해당 대화의 `chat_id`를 확인해서 `TELEGRAM_CHAT_ID`에 넣습니다.

### chat_id 찾는 방법

가장 쉬운 방법은 봇에 메시지를 한 번 보낸 뒤 아래 스크립트를 실행하는 것입니다.

```bash
python scripts/get_telegram_chat_id.py --bot-token <YOUR_BOT_TOKEN>
```

또는 환경 변수로 토큰을 넣어둔 상태라면:

```bash
python scripts/get_telegram_chat_id.py
```

실행 전에 꼭 아래 둘 중 하나를 먼저 해 주세요.

1. 봇과 1:1 대화를 시작하고 아무 메시지나 보내기
2. 받을 그룹에 봇을 초대한 뒤 그룹에 아무 메시지나 보내기

스크립트가 `chat_id=...` 형식으로 후보를 출력하면 원하는 값을 `TELEGRAM_CHAT_ID`에 넣으면 됩니다.

## GitHub Pages 켜기

1. GitHub 저장소 `Settings > Pages`로 이동합니다.
2. Source를 `Deploy from a branch`로 선택합니다.
3. Branch는 `main`, 폴더는 `/docs`를 선택합니다.
4. 저장 후 몇 분 지나면 웹 페이지가 열립니다.

## 커스터마이징 포인트

환경 변수로 아래 항목을 조정할 수 있습니다.

- `REPORT_PAGE_DEPTH`: 카테고리별로 몇 페이지까지 볼지
- `MUST_READ_LIMIT`: 필독 후보 개수
- `REPORT_CATEGORIES`: `company,industry,economy,invest,market,debenture`
- `BROKER_PRIORITY`: 우선순위를 높게 둘 증권사 목록
- `PRIORITY_SUBJECTS`: 관심 종목명 목록
- `PRIORITY_KEYWORDS`: 관심 섹터/테마 키워드 목록
- `PRIORITY_ONLY`: `true`면 필독/텔레그램을 관심 일치 리포트 중심으로 더 강하게 좁힘
- `REPORT_TIMEZONE`: 기본 `Asia/Seoul`

예시:

```text
PRIORITY_SUBJECTS=삼성전자,SK하이닉스,한화에어로스페이스
PRIORITY_KEYWORDS=반도체,방산,원자력,로봇
PRIORITY_ONLY=false
```

이 값을 넣으면 관심 종목/섹터가 제목이나 본문에 들어간 리포트가 더 높은 점수를 받고, 웹 화면에서도 `관심 항목만 보기`로 바로 좁혀볼 수 있습니다.

## 필독 선정 기준

현재는 완전한 AI 리서처가 아니라 규칙 기반 우선순위입니다.

- 카테고리 가중치
- 조회수
- 목표가/투자의견 포함 여부
- 우선 추적 증권사 여부
- 관심 종목/섹터 일치 여부
- 제목 키워드
- 본문 길이

즉시 쓸 수 있는 버전으로는 충분하지만, 나중에는 다음 확장이 좋습니다.

- OpenAI 같은 LLM으로 요약 품질 향상
- 산업/매크로/종목별 별도 랭킹
- 텔레그램에서 `/today`, `/company`, `/macro` 같은 명령어 지원
- 관심 섹터나 관심 종목 사용자별 구독
- 원문 PDF OCR 또는 텍스트 추출 기반 심화 요약

## 다음 단계 추천

지금 상태로도 GitHub에서 무인 자동 실행은 가능합니다. 실제 운영에 들어가기 전에 아래 순서로 마무리하면 좋습니다.

1. 저장소 생성 후 코드 업로드
2. GitHub Secrets 설정
3. Actions 수동 실행으로 첫 적재
4. Pages 활성화
5. 텔레그램 메시지 길이와 필독 선정 로직 튜닝
