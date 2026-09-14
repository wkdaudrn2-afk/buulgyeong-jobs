# 부울경 단기알바 1시간 자동 업데이트

무료 구성:
- GitHub Pages: `index.html` 공개
- GitHub Actions: 매시간 `collector.py` 실행
- `jobs.json`: 자동 갱신
- 휴대폰 화면: 5분마다 `jobs.json` 재확인

## 한 번만 설정
1. GitHub에서 새 **Public repository**를 만듭니다.
2. 이 ZIP의 파일을 저장소 루트에 전부 업로드합니다.
3. 저장소 `Settings → Pages → Build and deployment → Deploy from a branch`를 선택합니다.
4. Branch를 `main / (root)`로 저장합니다.
5. `Actions`에서 `hourly-job-update`를 한 번 `Run workflow`로 실행합니다.
6. 이후 생성되는 `https://사용자이름.github.io/저장소이름/` 주소를 카카오 오픈채팅에 고정합니다.

## 수집 기준
- 부산·경남·울산
- 등록/게시일 최근 3일 이내로 확인 가능한 것만
- 오늘/과거 근무 제외, 내일 이후
- 1~7일 근무
- 하루(1일) 알바 최우선
- 같은 조건이면 일급/일급 환산액 높은 순
- 행사·전시·설치·철거·물류·진열·보조 우선
- 중복 제거
- 등록일/근무일을 확인할 수 없으면 제외
- 401/403/429, 로그인, 캡차, robots.txt 제한은 우회하지 않고 건너뜀

## 중요
구인 사이트의 HTML 구조나 접근 정책이 바뀌면 특정 소스가 비어 있을 수 있습니다. 이 수집기는 접근 제한을 우회하지 않는 범위에서만 동작합니다.
