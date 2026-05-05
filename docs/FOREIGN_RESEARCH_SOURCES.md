# 해외 리서치 소스 조사 메모

검증 시점: 2026-04-20 (Asia/Seoul)

## 한 줄 결론

해외 `증권사 리포트`를 자동 수집하는 것은 가능하지만, 공개 웹에서 안정적으로 모을 수 있는 것은 대체로 `매크로/전략/하우스뷰/인사이트` 계열입니다. 우리가 흔히 떠올리는 `해외 셀사이드 개별 종목 리포트`는 상당수가 로그인 또는 고객 전용 포털 뒤에 있어 1차 자동화 범위에서 제외하는 편이 안전합니다.

## 공개 접근이 확인된 후보

| 우선순위 | 소스 | 성격 | 공개 여부 | 자동화 적합도 | 비고 |
| --- | --- | --- | --- | --- | --- |
| 1 | [BNP Paribas Economic Research](https://economic-research.bnpparibas.com/) | 매크로, 국가, 시장, 주간물 | 공개 | 매우 높음 | 아카이브와 상세 페이지 구조가 비교적 명확함 |
| 2 | [Deutsche Bank Research Institute](https://www.dbresearch.com/) | 매크로, 시장, 차트북, PDF | 공개 | 높음 | 검색/목록/상세/PDF 흐름이 확인됨 |
| 3 | [Nomura Connects](https://www.nomuraconnects.com/) | 이코노미, 중앙은행, 지역별 인사이트 | 공개 | 높음 | 주제/지역/상세 글 구조가 깔끔함 |
| 4 | [UBS CIO Insights / House View](https://www.ubs.com/global/en/wealthmanagement/insights.html) | 하우스뷰, 데일리, CIO Alert | 공개 일부 | 중상 | 공개 상세 글은 가능하지만 일부 깊은 링크는 `secure.ubs.com`으로 빠짐 |
| 5 | [Goldman Sachs Insights](https://www.goldmansachs.com/insights) | 매크로, 시장, 아웃룩, 리서치 요약 | 공개 | 중간 | 공개 글은 많지만 아카이브 구조가 균일하지 않음 |
| 6 | [Morgan Stanley IM Insights](https://www.morganstanley.com/im/en-us/institutional-investor/insights/all-insights.html) | 멀티에셋, 채권, 전략, PDF | 공개 일부 | 중간 | 상세 글/PDF는 열리지만 목록 진입에 지역/역할 선택 흐름이 있음 |

## 제외 권고

| 소스 | 제외 이유 |
| --- | --- |
| [J.P. Morgan Markets Research & Insights](https://markets.jpmorgan.com/research-and-insights) | 공식 페이지에 `Request Access`가 명시되어 있고 Markets 고객 전용임 |
| [J.P. Morgan Market Insights](https://markets.jpmorgan.com/research-and-insights/market-insights) | `Available only to J.P. Morgan Markets clients`가 명시됨 |
| [Macquarie Market Insights](https://www.macquarie.com/is/en/about/company/commodities-and-global-markets/research-and-market-insights.html) | `exclusive for Macquarie clients`와 별도 로그인 포털이 명시됨 |
| [Nomura Global Research Portal](https://www.nomuranow.com) | Nomura Connects 본문에서 별도 로그인 포털로 분리되어 있음 |
| UBS의 `secure.ubs.com` 링크 | 일부 시리즈는 보안 서브도메인으로 빠져 세션/접근 통제가 걸릴 가능성이 큼 |

## 소스별 메모

### 1. BNP Paribas Economic Research

- `Eco Week`, `Eco Flash`, `Eco Charts`, `Eco Insight` 등 발행물 단위로 분류되어 있습니다.
- 공개 아카이브에서 날짜, 제목, 저자, 요약이 보입니다.
- 국가/지역/테마 필터가 있어 후속 카테고리 매핑이 쉽습니다.
- 현재 프로젝트의 `economy`, `market`, `invest` 카테고리와 잘 맞습니다.

### 2. Deutsche Bank Research Institute

- 공개 검색/다운로드 페이지가 있고 최신 발행물 목록이 열립니다.
- 일부 문서는 HTML 상세와 `View PDF`를 함께 제공합니다.
- `Macro`, `Technology`, `Geopolitics`, `Corporate Landscape` 등 태그가 있어 분류에 유리합니다.
- 구조가 비교적 풍부해서 1차 구현 대상으로 적합합니다.

### 3. Nomura Connects

- 메인 페이지에서 지역, 주제, 타입 필터가 노출됩니다.
- 상세 글은 HTML 본문을 공개하고, 제목/요약/기여자 정보도 비교적 명확합니다.
- 다만 전형적인 `정식 리서치 PDF`보다는 `인사이트 아티클`에 가깝습니다.
- 해외 매크로/중앙은행/지역 이슈를 넓게 모으는 데는 매우 적합합니다.

### 4. UBS CIO / House View

- `House View`, `CIO Alert`, `Daily` 계열의 공개 페이지와 상세 글이 확인됩니다.
- `House View`는 일간/주간 구조가 보입니다.
- 다만 `Paul Donovan` 같은 일부 링크는 `secure.ubs.com`으로 이동해 범위를 좁혀야 합니다.
- 따라서 1차 자동화는 `House View Daily`, `CIO Alert` 같은 공개 경로만 대상으로 제한하는 것이 좋습니다.

### 5. Goldman Sachs Insights

- 공개 글과 Outlook 허브는 잘 열립니다.
- `Goldman Sachs Research`나 `Outlooks` 허브에서 매크로/시장 관련 글을 읽을 수 있습니다.
- 다만 모든 항목이 동일한 템플릿으로 정렬되어 있지 않아 목록 파싱 난도가 조금 더 높습니다.
- 1차보다는 2차 확장 대상으로 두는 편이 안전합니다.

### 6. Morgan Stanley IM Insights

- 상세 아티클과 `Download PDF` 링크가 확인됩니다.
- `The BEAT`, `Global Fixed Income Bulletin` 같은 반복 시리즈가 있어 수집 가치는 있습니다.
- 반면 상위 목록 진입에 지역/역할 선택 흐름이 있어 배치 수집 시 예외 처리가 필요할 수 있습니다.
- 구현은 가능하지만 1차 대상보다 운영 리스크가 큽니다.

## 현재 프로젝트에 맞는 현실적인 범위

### 1차 자동화 범위

- BNP Paribas Economic Research
- Deutsche Bank Research Institute
- Nomura Connects
- UBS House View 공개 경로

이 범위의 공통점:

- 로그인 없이 상세 본문 또는 메타데이터 접근 가능
- 날짜, 제목, URL이 공개 페이지에서 확인 가능
- 매일/매주 반복 발행물이 있어 수집기 가치가 큼
- 현재 `Report` 모델의 `title`, `broker`, `published_date`, `detail_url`, `body`, `summary`에 무리 없이 매핑 가능

### 2차 확장 범위

- Goldman Sachs Insights / Outlooks
- Morgan Stanley IM Insights

이 범위의 공통점:

- 공개 접근 자체는 가능하지만
- 목록 구조가 덜 균일하거나
- 지역/역할 선택, 동적 렌더링, 링크 체계 차이로 운영 비용이 더 큼

### 제외 범위

- 고객 전용 Markets 포털
- 로그인/세션 전제 사이트
- 유료/권한 기반 전용 리서치 포털
- 완전한 개별 종목 셀사이드 리포트 원문만을 목표로 하는 수집

## 현재 코드 구조 기준 설계 방향

현재 파이프라인은 `src/report_collector/main.py`에서 collector 목록을 고정 등록하고, 각 collector가 `list -> detail -> Report` 흐름으로 데이터를 채웁니다.

해외 소스를 붙일 때도 같은 패턴으로 가면 됩니다.

1. `src/report_collector/sources/` 아래에 소스별 collector 추가
2. `collect(target_date)`에서 목록 페이지를 순회
3. 상세 페이지에서 본문, 저자, PDF 링크를 보강
4. 기존 `Report` 모델에 매핑
5. `main.py`의 collector 목록에 연결

## 카테고리 매핑 제안

| 해외 소스 유형 | 현재 카테고리 |
| --- | --- |
| macro, economy, central bank | `economy` |
| markets, asset allocation, house view | `market` 또는 `invest` |
| sector, industry outlook | `industry` |
| company-specific equity note | `company` |

주의할 점:

- 해외 공개 소스는 `company`보다 `economy`, `market`, `invest` 비중이 훨씬 높을 가능성이 큽니다.
- 따라서 현재 점수 로직은 국내 종목 리포트 중심으로 짜여 있어, 해외 소스가 들어오면 `market/economy` 쪽 가중치와 키워드 룰을 따로 조정하는 편이 좋습니다.

## 추천 구현 순서

1. BNP Paribas Economic Research collector
2. Deutsche Bank Research collector
3. Nomura Connects collector
4. UBS House View collector
5. Goldman Sachs collector
6. Morgan Stanley collector

이 순서를 추천하는 이유는 `공개성`, `구조 안정성`, `운영 리스크`, `현재 모델과의 적합성`이 가장 좋기 때문입니다.

## 운영 판단

- `해외 증권사 리포트 수집`은 가능
- 다만 첫 버전은 `공개 매크로/전략 리서치` 중심으로 시작하는 것이 맞음
- `해외 개별 종목 셀사이드 리포트 원문` 수집은 별도 권한/계약 이슈 때문에 기본 범위에서 빼는 것이 안전함

## 다음 구현 후보

가장 무난한 1차 작업은 아래 둘 중 하나입니다.

1. `BNP Paribas + Deutsche Bank` 2개 소스를 먼저 붙여 해외 매크로/시장 리포트 수집 시작
2. `Nomura + UBS`까지 포함해 공개 HTML 중심 4개 소스를 한 번에 붙이기
