# CLIProxy 상태바

Codex 기본 상태바는 고정 항목만 지원한다. Claude Code의 외부 스크립트 방식과 다르다. CLIProxy 정보를 Codex 하단에 상시 표시하려면 별도 패치가 필요하다.

## 실제 사용 계정

Codex 상태바가 전달한 `session.id`를 CLIProxy 요청의 `Thread-Id`와 연결한다. `Session-Id`는 캐시 친화성 키일 수 있어 계정 식별에 사용하지 않는다. CLIProxy의 기존 계정 선택 콜백에서 `auth_index`를 기록하므로 첫 응답 토큰이 나오기 전에도 조회할 수 있다. 재시도마다 선택된 계정이 갱신된다. 우선순위나 계정 목록 순서로 사용 계정을 추측하지 않는다.

관리 키로 보호된 `GET /v8/management/observability/routing/session?session_id=<UUID>`가 해당 세션의 선택 계정과 요청 진행 여부를 반환한다. 요청 중에는 ‘응답 중’을 표시하고 종료되면 해당 문구를 숨긴다. 같은 세션에서 요청이 겹치면 가장 최근 선택을 표시한다. 서로 다른 세션·하위 에이전트의 Thread-Id는 별도로 관리한다. 추적 정보는 메모리에 최대 4,096개·6시간 보관하며 서버 재시작 후 첫 요청 전에는 대기 상태를 표시한다. 여러 프록시 노드의 추적 상태를 합치는 기능은 없다.

`bin/cliproxy-statusline`은 선택 계정의 인덱스를 기존 로컬 수집기 `/api/accounts` 캐시에 연결한다. 운영 사용량 큐를 추가로 소비하거나 제공자 쿼터 API를 호출하지 않는다. 계정 선택은 0.5초 간격으로 확인하고, 잔여량 자체는 기존 수집기의 120초 캐시를 사용한다. 오래된 캐시와 조회 실패를 표시한다.

```text
Codex · 업무 계정 · Pro · 응답 중
Usage ███░░░░░░░ 30% (4h 55m / 5h) | ██████░░░░ 60% (4d 20h / 7d)
```

위 수치는 가상이다. 계정 별칭을 우선 표시하고, 별칭이 없으면 메일 사용자명 또는 인증 파일 이름을 사용한다. 초기화까지의 시간을 짧은 상대 시간으로 표시한다. 위젯과 동일한 플랜 표시 함수를 사용한다. 퍼센트와 막대는 사용량을 의미하며, 소진에 가까워지면 초록에서 노랑·빨강으로 바뀐다. 터미널의 `NO_COLOR` 설정은 Codex가 그대로 따른다. 별도 실행기는 위젯의 언어 설정과 `CLIPROXY_LANGUAGE`를 따른다.

```bash
./bin/cliproxy-codex
# 세션 안에서 /cliproxy-statusline 명령으로 켜기/끄기

# 독립 조회에는 현재 Codex 세션 UUID가 필요하다.
./bin/cliproxy-statusline --session-id <UUID> --language en
```

수집기는 기존처럼 `./bin/cli-proxy-quota dashboard --no-open`으로 실행한다. 세션에 선택된 계정이 없으면 ‘연결 대기’, 계정 쿼터가 아직 없으면 ‘쿼터 조회 대기’를 표시한다. 추적 API·수집기 연결 실패는 ‘계정 연결 확인 불가’로 표시하며 다른 계정 정보로 대신하지 않는다. 관리 키·인증 토큰·입력 JSON·실제 계정 정보는 로그나 저장소에 기록하지 않는다. 일반 명령은 오류 종료하고, Codex 렌더러는 오류 상태를 표시하기 위해 정상 종료한다.

## CLIProxy 서버 패치

`codex-statusline/cliproxy-v8.0.4.patch`는 CLIProxyAPI 커밋 `d33f63f8e3d98428440ebca5a5b6a981a61ff71e`를 기준으로 한다. 기존 계정 선택·쿨다운·OAuth·사용량 집계 코드는 변경하지 않는다. 기존 선택 콜백을 유지하면서 세션 관찰을 추가하고 관리 API를 등록한다. CLIProxy MIT 라이선스는 `CLIPROXY_LICENSE`에 보관한다.

해당 버전의 별도 소스 체크아웃에 패치를 적용하고, 기존 빌드 절차로 서버를 빌드한다.

```bash
git apply /path/to/CLIProxy-quota/codex-statusline/cliproxy-v8.0.4.patch
go test -race ./sdk/api/handlers ./internal/api -run 'TestSessionAccount|TestRequestExecutionMetadata|TestManagementV8'
go build -o cli-proxy-api ./cmd/server
```

배포 전에 기존 포트·환경·인증·설정·로그·플러그인 마운트를 비교한다. 로컬 운영 이미지는 기존 `v8.0.4-xhigh` 기본 레이어와 실행 설정을 보존한 `v8.0.4-xhigh-hud`이며 기존 xhigh 변경도 포함한다. 관리 화면은 빌드한 `.local/management.html`을 `/CLIProxyAPI/static/management.html`에 읽기 전용으로 연결해 컨테이너 재생성에도 보존한다. 설정 파일·인증 파일을 이미지에 포함하지 않는다.

## 별도 Codex 실행기

공식 `openai/codex`의 `rust-v0.160.0` 커밋 `a956835d020762cb2b570053af06f643a11c0ecc`에 패치를 적용한다. 외부 상태바 실행·비동기 갱신·제한 시간·멀티라인 렌더링은 [cxstatusline](https://github.com/adrijshikhar/cxstatusline)의 `4e5293425d1f37dde096fb5a49ebfd3b67fd62bb`에서 제공한 0.160.0 패치를 재사용했다. 여기에 `/cliproxy-statusline` 명령으로 세션 안에서 켜기/끄기를 추가한다. 기존 `/statusline` 선택기는 유지한다.

cxstatusline 앱·설치기·자체 데몬은 실행하지 않는다. `CXSTATUSLINE_COMMAND`는 별도 실행기 안에서만 설정한다. 기존 `codex` 명령·Codex 설정·hooks·세션 ID·인증 데이터는 교체하지 않는다. 별도 실행기는 `--no-daemon`으로 실행해 기존 공유 대몬을 교체하지 않는다.

```bash
uv run --no-project --python /usr/bin/python3 python scripts/build_statusline_codex.py
./bin/cliproxy-codex
```

패치 파일은 `codex-statusline/codex-0.160.0.patch`이며 Codex Apache-2.0·cxstatusline MIT 고지를 함께 보관한다. 버전이 다르면 빌드 스크립트는 중단한다. Rust 1.95.0과 공식 Codex의 네이티브 빌드 의존성이 필요하다.

공식 릴리스의 Cargo.lock은 내부 패키지 버전이 0.0.0이고 Cargo.toml은 0.160.0이어서 원본에서도 `--locked` 빌드가 중단된다. 패치에는 내부 패키지 버전 159개를 0.160.0으로 일치시키는 변경이 포함되며, 외부 의존성 버전·체크섬은 변경하지 않는다. 빌드는 계속 `--locked`로 수행한다.

2026-10-03 검증: Python 테스트 30개와 상태바 관련 Rust 테스트 13개가 통과했다. 기존 콜백 유지·재시도·세션 분리·WebSocket 업그레이드 헤더 보호를 포함한 Go 테스트가 race 검사와 함께 통과했다. 격리 서버에서는 첫 응답 토큰 전에 계정 선택이 보이는 것과 요청 종료 상태를 확인했다. 실제 TUI에서 한글·색상·계정 변경을 확인했고 운영 연결의 짧은 검증 요청에서 응답 중 선택 계정 표시·쿼터 캐시 일치·완료 후 상태 문구 제거을 확인했다. 기존 포트·환경·설정 파일·인증 계정·기존 마운트는 적용 전후 비교로 동일함을 확인했다. 운영 큐는 기존 수집기 하나만 소비한다.

기존 `codex` 명령은 교체하지 않았다. 이 기능은 공식 외부 스크립트 API가 아니라 버전을 고정한 로컬 패치이며 기존 Codex 자동 업데이트와 별개다. 빌드하지 않은 실행기는 오류로 중단한다. 수집기나 서버 추적 연결이 실패하면 다른 계정을 추측해 표시하지 않는다.
