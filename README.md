# 증권사 리포트 데일리 봇

컴퓨터를 켜두지 않아도 돌아가게 만들기 위해, 이 프로젝트는 `GitHub Actions + GitHub 저장소 + GitHub Pages + Telegram Bot` 조합을 기본 구조로 잡았습니다.

## 이 프로젝트가 하는 일

- 네이버 금융 리서치와 일부 증권사 공식 리서치 페이지를 함께 수집합니다.
- 날짜별로 `storage/archive/YYYY-MM-DD/` 아래에 저장합니다.
- 리포트별 메타데이터, 링크, 짧은 요약, 옵션형 LLM 투자 메모, 우선순위 점수를 만듭니다.
- 우선 검토 후보 리포트를 자동 선별해서 텔레그램으로 보냅니다.
- 같은 데이터를 `docs/`에도 생성해서 GitHub Pages로 웹에서 다시 볼 수 있게 합니다.
- 수집 소스별 성공/무출력/실패 상태와 소요 시간을 기록해서 운영 이상 징후를 확인합니다.
- 실패한 소스와 최근 평균 대비 수집량이 급감한 소스를 운영 알림으로 노출합니다.
- 종목별 JSON에는 이익/마진 추정치 흐름, 목표가 추이, 의견 분포, 최근 2주 증권사 타임라인용 차트 데이터가 포함됩니다.
- 우선 검토 후보로 선정된 리포트는 1일/7일/30일 성과 추적 원장에 기록됩니다.

중요: 저작권과 저장소 용량을 고려해서 원문 PDF나 본문 전체를 저장하지 않고, 메타데이터와 짧은 요약 중심으로 보관합니다.

## 현재 수집 소스

- `네이버 금융 리서치`: 기본 수집원입니다.
- `미래에셋증권 공식 리서치`: 공개 목록과 상세 페이지를 직접 수집합니다.
- `한국투자증권 공식 리서치`: 공개 상세 페이지를 직접 수집합니다.
- `신한투자증권 공식 리서치`: 공식 공개 JSON 목록에서 기업/산업/시황/경제 리포트를 수집합니다.

참고:
- 한국투자증권은 현재 공개 PDF 원문 링크가 로그인 체크 뒤에 열리는 구조라서, 상세 페이지 본문 중심으로 수집합니다.
- 공식 소스와 네이버에서 같은 리포트가 겹치면 공식 소스를 우선 보관합니다.

## 권장 운영 구조

1. GitHub 저장소에 이 프로젝트를 올립니다.
2. Telegram Bot 토큰과 Chat ID를 GitHub Secrets에 넣습니다.
3. GitHub Actions가 평일 저녁 정해진 시각에 자동 실행됩니다.
4. 결과는 저장소에 커밋되고, 텔레그램으로 요약이 발송됩니다.
5. GitHub Pages를 켜면 웹 대시보드에서도 날짜별로 탐색할 수 있습니다.

기본 스케줄은 평일 `09:00 KST` 수집, `15:30 KST` 업데이트입니다.
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

간단한 회귀 테스트는 아래처럼 실행합니다.

```bash
python -m unittest discover -s tests
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
- `MUST_READ_LIMIT`: 우선 검토 후보 개수
- `MUST_READ_BROKER_SOFT_LIMIT`: 우선 검토 후보를 처음 채울 때 한 증권사에 허용할 기본 상한
- `MUST_READ_BROKER_HARD_LIMIT`: 후보가 부족할 때도 넘기지 않을 증권사별 보조 상한
- `MUST_READ_SUBJECT_HARD_LIMIT`: 후보가 부족할 때도 넘기지 않을 동일 종목/제목별 보조 상한
- `MARKET_DATA_ENABLED`: 기본 `true`; 후보 성과 추적에 종가/거래량 데이터를 연결
- `MARKET_DATA_SOURCE`: 기본 `naver`; 현재는 네이버 일별 시세를 사용
- `MARKET_DATA_MAX_PAGES`: 종목별 일별 시세를 몇 페이지까지 조회할지
- `MARKET_BENCHMARK`: 기본 `KOSPI`; 후보 수익률과 비교할 벤치마크 지수 (초과수익 계산)
- `SUBJECT_TICKER_MAP`: 공식 리포트처럼 종목코드가 없는 후보를 보강하는 매핑. 예: `삼성전자=005930,NAVER=035420`. 아카이브에 쌓인 네이버 리포트의 종목코드에서 자동 학습되므로 보통 비워둬도 됩니다.
- `REPORT_CATEGORIES`: `company,industry,economy,invest,market,debenture`
- `BROKER_PRIORITY`: 우선순위를 높게 둘 증권사 목록
- `PRIORITY_SUBJECTS`: 관심 종목명 목록
- `PRIORITY_KEYWORDS`: 관심 섹터/테마 키워드 목록
- `PRIORITY_ONLY`: `true`면 우선 검토 후보/텔레그램을 관심 일치 리포트 중심으로 더 강하게 좁힘
- `REPORT_TIMEZONE`: 기본 `Asia/Seoul`
- `OPENAI_SUMMARY_ENABLED`: 기본 `false`; `true`로 켜야 LLM 요약과 구조화 투자 메모가 실행됨
- `OPENAI_API_KEY`: `OPENAI_SUMMARY_ENABLED=true`일 때 사용할 OpenAI API 키
- `OPENAI_SUMMARY_MAX_REPORTS`: LLM으로 보강할 최대 리포트 수

예시:

```text
PRIORITY_SUBJECTS=삼성전자,SK하이닉스,한화에어로스페이스
PRIORITY_KEYWORDS=반도체,방산,원자력,로봇
PRIORITY_ONLY=false
```

이 값을 넣으면 관심 종목/섹터가 제목이나 본문에 들어간 리포트가 더 높은 점수를 받고, 웹 화면에서도 `관심 항목만 보기`로 바로 좁혀볼 수 있습니다.

## 우선 검토 후보 선정 기준

현재는 완전한 AI 리서처가 아니라 규칙 기반 우선순위입니다. PDF 링크가 확보된 리포트는 대시보드와 텔레그램에서 PDF를 대표 링크로 먼저 사용하고, 상세 페이지 링크는 보조로 남깁니다.

- 카테고리 가중치
- 조회수
- 영업이익, 순이익, EPS, OPM 같은 추정치 숫자와 목표가/투자의견 포함 여부
- 우선 추적 증권사 여부
- 관심 종목/섹터 일치 여부
- 제목 키워드
- 본문 길이
- EPS/매출/이익 추정치 숫자가 직전 리포트 대비 상향/하향됐는지 (수치 비교 기반, 목표가보다 높은 가중치)
- 이익 추정 상향, 마진 개선, 목표가/의견/애널리스트 변화 감지 여부
- 공식 소스 여부와 PDF 본문 확보 여부
- 동일 종목과 특정 증권사 쏠림을 줄이는 다양성 규칙
- 점수 분해 내역과 링크 상태를 대시보드에 노출
- 우선 검토 후보 선정 결과의 1일/7일/30일 성과 추적 원장

## 텔레그램 명령어 봇

일일 발송과 별도로 저장된 `docs/data`를 조회해서 답하는 명령어 봇 스크립트를 추가했습니다.

```bash
python scripts/telegram_command_bot.py --timeout 20
```

지원 명령어:

- `/today`: 최신 데일리 우선 검토 후보
- `/changes`: 이익 추정/마진율/목표가/의견/애널리스트 변화 감지 리포트
- `/subject 삼성전자`: 종목별 최근 2주 증권사 타임라인과 최신 리포트
- `/source`: 수집 소스 상태와 운영 알림
- `/watchlist`: 관심 종목/키워드 일치 리포트

명령어 봇은 `docs/data/telegram_command_state.json`에 Telegram update offset을 저장합니다. GitHub Actions처럼 매번 깨끗한 환경에서 짧게 실행하려면 이 상태 파일을 보존하는 실행 환경이 필요합니다.

## 선정 성과 추적

우선 검토 후보는 `docs/data/performance/selection_outcomes.json`에 누적됩니다. 각 리포트에 대해 1일/7일/30일 horizon과 due date를 남기고, due date가 지나면 보유 아카이브에서 같은 종목/제목의 후속 리포트, 변화 감지 수, 최신 목표가/의견을 자동으로 채웁니다. 종목코드가 확보된 후보는 네이버 일별 시세에서 entry/exit 종가와 거래량을 조회해 `price_return_pct`, `volume_change_pct`도 함께 채웁니다.

- 종목코드가 없는 공식 리포트는 아카이브에 쌓인 네이버 리포트의 종목/코드 쌍에서 자동으로 학습해 보강합니다. 예외적인 경우만 `SUBJECT_TICKER_MAP`으로 직접 지정하면 됩니다.
- 같은 기간의 `MARKET_BENCHMARK`(기본 KOSPI) 지수 수익률을 함께 조회해 `index_return_pct`와 `excess_return_pct`(시장 대비 초과수익)를 기록합니다.
- 요약에는 horizon별 평균수익률/적중률/평균 초과수익과 점수 구간별·카테고리별·증권사별 분해가 포함되고, 웹 대시보드 `선정 성과` 섹션에서 바로 볼 수 있습니다.
- `news_count`는 별도 뉴스 공급원 연결 전까지 `null`로 유지됩니다.

## 추정치 변화 추적 (LLM 없이)

직전 리포트와 같은 (지표, 기간)의 추정치 숫자를 직접 비교해서 EPS/매출액/영업이익/순이익/마진율 추정이 상향됐는지 하향됐는지 감지합니다. 단위가 달라도(조원 vs 억원) 환산 후 비교하고, ±1% 미만(마진은 ±0.1%p 미만)의 잡음은 무시합니다. 감지된 변화는 `estimate_revisions`로 저장되고 우선순위 점수, 변화 감지 목록, 텔레그램 메시지에 반영됩니다. 목표가 변화보다 높은 가중치를 받습니다. 감지된 신호를 종합한 규칙 기반 톤(`stance`: positive/negative/neutral)도 함께 기록되므로 LLM 없이도 리포트 방향성을 볼 수 있습니다.

즉시 쓸 수 있는 버전으로는 충분하지만, 나중에는 다음 확장이 좋습니다.

- OpenAI 같은 LLM으로 요약과 투자 메모 품질 향상. 현재는 기본 비활성화 상태입니다.
- 산업/매크로/종목별 별도 랭킹
- 텔레그램 메시지는 운영 알림과 변화 감지를 먼저 보여주고, 문제가 없는 소스의 상세 헬스체크는 생략합니다.
- 텔레그램 명령어 봇을 상시 실행 환경이나 웹훅 구조로 격상
- 관심 섹터나 관심 종목 사용자별 구독
- 원문 PDF OCR 또는 텍스트 추출 기반 심화 요약
- 운영 알림 임계값과 알림 채널 세분화

## 다음 단계 추천

지금 상태로도 GitHub에서 무인 자동 실행은 가능합니다. 실제 운영에 들어가기 전에 아래 순서로 마무리하면 좋습니다.

1. 저장소 생성 후 코드 업로드
2. GitHub Secrets 설정
3. Actions 수동 실행으로 첫 적재
4. Pages 활성화
5. 주가/거래량/뉴스 데이터 연결로 선정 성과 원장 채우기
