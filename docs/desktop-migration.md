# Desktop Migration

이 문서는 목적지 Windows Desktop에서 코딩 에이전트가 그대로 실행할 수 있는 인수인계 절차다. 저장소 URL과 경로는 실제 값으로 바꿔야 한다.

## Agent instructions

다음 규칙을 반드시 지킨다.

1. 2026-10-06에는 `collect-once`를 실행하지 않는다. 오늘 날짜를 다시 수집하지 않는다.
2. 소스 장비의 수집과 스케줄러는 인수인계 후 계속 중지 상태로 둔다.
3. Git에는 코드와 문서만 맡긴다. `data/`, `.env`, `config.toml`, `private/`는 `.gitignore` 대상이므로 Git이 옮겨 주지 않는다. 무시된 파일을 `git add -f`로 추가하지 않는다.
4. 인증 파일, 토큰 파일, 브라우저 프로필, `.env`, `private/`를 전송하지 않는다. 인증은 Desktop에서 새로 만든다.
5. SQLite는 깨끗하게 닫힌 `data/live.sqlite3` 하나만 복사한다. `live.sqlite3-wal`, `live.sqlite3-shm`, fixture DB, export 파일과 백업 파일은 복사하지 않는다.
6. Desktop 스케줄러는 다음 Asia/Seoul 날짜가 될 때까지 비활성 상태로 둔다.
7. 두 장비가 같은 운영 DB에 동시에 쓰지 않게 한다.

## 현재 소스 스냅샷

소스의 마지막 정상 라이브 수집은 2026-10-06 기준 `SUCCESS`다.

- 시설: 44/44
- 관측: 314건
- 본인 예약 행: 4건
- `data/live.sqlite3` SHA-256: `139a127a45bb56246a563483048cd2834ffcde90612b0d0792031e77ce08aa7f`

같은 날짜에 `AUTH_REQUIRED` 감사 실행 기록도 하나 있다. 정상 성공 스냅샷과 별개의 감사 기록이며 무해하므로 삭제하거나 재수집으로 보정하지 않는다.

## 1. 소스 장비 중지

소스 장비에서 스케줄러와 수동 수집 프로세스를 먼저 중지한다. 현재 실행 중인 `collect-once`가 있다면 정상 종료될 때까지 기다린다. SQLite 파일이 열린 상태가 아닌지 확인한 뒤, 수집과 스케줄러를 인수인계가 끝난 뒤에도 계속 중지한다.

소스 저장소의 현재 커밋을 기록한다.

```powershell
git rev-parse HEAD
```

## 2. Git으로 코드 전송

Desktop에서 원하는 경로와 저장소 URL을 사용해 코드를 받는다.

```powershell
git clone <REPO_URL> <DESTINATION_REPO_PATH>
Set-Location <DESTINATION_REPO_PATH>
uv sync
uv run playwright install chromium
```

Git으로 옮겨지는 것은 추적된 코드와 문서뿐이다. `.gitignore` 때문에 `data/`, `.env`, `config.toml`, `private/`는 clone에 포함되지 않는다.

## 3. 소스에서 전송할 파일

소스 수집이 완전히 멈추고 DB가 닫힌 뒤, 승인된 사설 파일 전송 경로로 아래 파일 하나만 복사한다.

```text
data/live.sqlite3
```

복사하지 않을 파일은 다음과 같다.

```text
data/live.sqlite3-wal
data/live.sqlite3-shm
data/fixture.sqlite3
data/exports/
data/backups/
private/
.env
```

`config.toml`도 전송하지 않는다. Desktop에서 예제 파일을 바탕으로 직접 만든다.

## 4. Desktop 설정 재생성

Desktop 저장소에서 설정 파일을 만든다. 경로는 Desktop 환경에 맞게 편집한다.

```powershell
Copy-Item config.example.toml config.toml
notepad config.toml
```

`config.toml`의 `live_db`, `fixture_db`, 인증 상태 경로, API URL, 사이트 URL을 Desktop 경로에 맞춘다. `live_db`와 `fixture_db`는 서로 다른 파일이어야 한다.

그 다음 필요한 로컬 디렉터리를 만든다.

```powershell
New-Item -ItemType Directory -Force data, private, data/exports, data/backups | Out-Null
```

## 5. DB 배치

전송한 닫힌 DB를 Desktop 저장소의 `data/live.sqlite3`에 둔다. 기존 파일이 있다면 덮어쓰지 말고 인수인계 대상이 맞는지 확인한 뒤 교체한다. WAL이나 SHM 파일을 만들어 맞추려 하지 않는다.

```powershell
Copy-Item <TRANSFERRED_LIVE_DB_PATH> data/live.sqlite3
```

## 6. 인증 재생성

Desktop에서 `.env`를 수동으로 만든다. 실제 자격 증명 값은 이 문서나 Git에 기록하지 않는다.

```powershell
notepad .env
```

`.env`에는 프로젝트가 요구하는 `ID`와 `PASSWORD`를 로컬 보안 방식으로 입력한다. 인증 파일과 토큰 파일은 소스 장비에서 가져오지 않는다.

설정한 `.env`로 Desktop에서 새 인증 상태를 만든다.

```powershell
uv run gist-studyroom --config config.toml login --from-env --replace
```

명령이 완료되면 인증 상태와 API 토큰은 Desktop의 설정된 `private/` 경로에 새로 생성된다. 값이 출력되거나 문서에 기록되지 않았는지 확인한다.

## 7. DB와 체크섬 검증

먼저 복사된 DB의 SHA-256을 확인한다. 결과가 아래 값과 다르면 수집이나 스케줄러를 시작하지 말고 복사를 다시 확인한다.

```powershell
Get-FileHash .\data\live.sqlite3 -Algorithm SHA256
```

기대값은 다음과 같다.

```text
139a127a45bb56246a563483048cd2834ffcde90612b0d0792031e77ce08aa7f
```

DB가 배치된 뒤 상태를 조회한다. 이 명령은 새 라이브 수집을 하지 않는다.

```powershell
uv run gist-studyroom --config config.toml status
```

상태와 체크섬이 현재 소스 스냅샷과 맞는지 확인한다. 2026-10-06의 `AUTH_REQUIRED` 감사 실행 하나는 정상적으로 남아 있어도 된다.

## 8. 다음 서울 날짜의 스케줄러 준비

2026-10-06에는 아래 명령을 실행하지 않는다.

```powershell
# 2026-10-06에는 실행 금지
uv run gist-studyroom --config config.toml collect-once
```

Desktop 스케줄러는 먼저 비활성 상태로 둔다. Asia/Seoul 기준으로 2026-10-06 다음 날짜가 시작된 뒤, 설정과 인증과 체크섬을 다시 확인하고 나서 스케줄러를 활성화한다. 그 첫 실행은 다음 날짜의 라이브 수집으로만 수행한다.

```powershell
uv run gist-studyroom --config config.toml collect-once
```

첫 실행이 정상 확인된 뒤에만 절대 경로를 사용하는 시간별 스케줄러를 등록한다. 스케줄러 등록 방식과 로그 경로는 [scheduling.md](scheduling.md)를 따른다. 소스 장비의 수집은 계속 중지 상태여야 한다.
