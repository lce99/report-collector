# GitHub 업로드 체크리스트

## 1. 로컬 준비

```bash
python -m pip install -r requirements.txt
python run_daily.py --skip-telegram --date 2026-04-16
```

로컬에서 한 번 돌아가면 GitHub로 올릴 준비가 된 것입니다.

## 2. Git 초기화

```bash
git init
git branch -M main
git add .
git commit -m "feat: bootstrap broker report collector"
```

이미 Git 저장소라면 `git init`은 생략해도 됩니다.

## 3. GitHub 저장소 만들기

### 방법 A. 웹에서 생성

1. GitHub에서 새 저장소를 생성합니다.
2. 로컬 저장소에 원격을 연결합니다.

```bash
git remote add origin https://github.com/<your-id>/<repo-name>.git
git push -u origin main
```

### 방법 B. GitHub CLI 사용

```bash
gh repo create <repo-name> --public --source=. --remote=origin --push
```

## 4. GitHub Secrets 설정

저장소 `Settings > Secrets and variables > Actions`에 아래 값을 넣습니다.

- Secret: `TELEGRAM_BOT_TOKEN`
- Secret: `TELEGRAM_CHAT_ID`

## 5. GitHub Variables 설정

관심 필터는 Secret이 아니라 Variable로 두는 편이 편합니다.

- Variable: `PRIORITY_SUBJECTS`
- Variable: `PRIORITY_KEYWORDS`
- Variable: `PRIORITY_ONLY`

예시:

```text
PRIORITY_SUBJECTS=삼성전자,SK하이닉스,한화에어로스페이스
PRIORITY_KEYWORDS=반도체,방산,원자력,로봇
PRIORITY_ONLY=false
```

## 6. 첫 실행

1. `Actions` 탭에서 `Daily Broker Report Digest` 워크플로를 수동 실행합니다.
2. 실행이 끝나면 `storage/`와 `docs/` 갱신 커밋이 생기는지 확인합니다.
3. 텔레그램 메시지가 잘 오는지 확인합니다.

## 7. GitHub Pages 켜기

1. `Settings > Pages`로 이동합니다.
2. Source를 `Deploy from a branch`로 선택합니다.
3. Branch는 `main`, 폴더는 `/docs`로 설정합니다.

## 8. 운영 체크 포인트

- 원하는 발송 시각으로 cron 수정
- `PRIORITY_SUBJECTS`와 `PRIORITY_KEYWORDS` 튜닝
- 필독 후보 개수와 증권사 우선순위 조정
- Actions 실패 시 외부 사이트 응답 구조가 바뀌었는지 점검

