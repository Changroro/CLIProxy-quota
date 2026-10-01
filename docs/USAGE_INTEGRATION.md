# 공식 관리 화면 Usage 패치와 수집 범위

2026-10-01 조사·구현 기록. 기본 관리 화면의 `#/usage`에서 기존 CLIProxy-quota 토큰 이력을 표시한다. 프록시 서버의 메모리 통계 기능을 복원하지 않는다.

## 소스와 패치

패치 대상은 서버 저장소 `CLIProxyAPI`가 아니라 공식 프런트엔드 [Cli-Proxy-API-Management-Center](https://github.com/router-for-me/Cli-Proxy-API-Management-Center)다. 우리 작업 저장소 내부 `.local/management-center`에 공식 소스를 클론했고 `feat/usage-companion` 브랜치에서 개발한다. 기준 커밋은 `a7ec312fbbb0a13f3a580ee0c7e29228a07c8867`이다.

재현 가능한 변경은 `management-theme/usage.patch`에 보관한다. 공식 사이드바·보호된 라우트·Usage 컴포넌트·기존 4개 언어의 안내 문구만 포함한다. 미니멀 SCSS 테마는 이 패치와 분리한다. 기존 빌드 스크립트가 테마와 Usage 패치를 함께 적용하고 공식 테스트·린트·TypeScript/Vite 빌드를 실행한다. 패치가 이미 적용됐는지 역방향 검사로 확인하며, 버전/내용이 맞지 않으면 실패한다.

```bash
uv run --no-project --python /usr/bin/python3 python scripts/build_management.py
./bin/cli-proxy-quota dashboard --no-open
./bin/cli-proxy-quota open
```

관리 URL의 `#/usage`를 열면 기존 관리 로그인으로 연결한다. 기간·서비스·계정·모델 필터, 입력/출력/캐시/총 토큰, 일별·계정별 그래프는 기존 화면을 그대로 재사용한다. GTK 위젯과 별도 `open-history`도 유지한다. 새로운 화면에서 운영 큐를 읽지 않으며 수집기 하나만 소비한다.

## 인증과 화면 연결

공식 화면은 브라우저의 로컬 `http://127.0.0.1:8318/api/management-session`으로 기존 관리 키와 프록시 주소를 보낸다. 로컬 서버는 설정된 관리 화면 Origin, 관리 키, 프록시 주소가 모두 일치할 때만 이력 세션 토큰을 발급한다. 리디렉션은 금지하고 연결은 10초 뒤 중단한다. 키를 빌드 결과·URL·SQLite에 넣지 않는다.

이력 화면은 iframe 안에서 기존 세션 교환을 수행한다. CSP의 `frame-ancestors`는 연결된 관리 화면 Origin만 허용한다. CORS는 인증 연결 엔드포인트 하나에만 허용하며, 기존 집계 API는 같은 Origin·로컬 세션 검증을 유지한다. 테마/언어 메시지는 송신 Origin과 iframe 창을 함께 확인한다. 필터를 초기화하지 않고 라이트·다크 전환을 반영한다. 공식 로그인 연결을 바꾸거나 로그아웃하면 이전 iframe을 재사용하지 않는다.

현재 수집기 주소는 브라우저 PC의 루프백이다. **서버에 들어오는 외부 API 요청의 집계는 가능하지만 다른 PC에서 관리 화면을 열었을 때 그 PC에 수집기가 없으면 Usage 탭은 연결되지 않는다.** 원격 관리까지 제공하려면 서버 측 플러그인/통계 API와 동일 출처 호스팅이 필요하다. 임의 외부 주소로 관리 키를 보내는 설정은 추가하지 않았다.

## 로컬·외부 호출의 정확한 범위

호출자의 위치가 아니라 **어느 CLIProxy 서버를 거쳤고 수집기가 어느 서버의 큐를 읽는지**가 기준이다.

| 요청 경로 | 현재 로컬 이력 |
| --- | --- |
| 이 PC의 앱 → 이 PC의 CLIProxy | 수집 가능 |
| 외부 PC/서비스 → 이 PC의 CLIProxy | 동일하게 수집 가능 |
| 이 PC/외부 PC → 다른 VPS의 CLIProxy | 현재 수집기가 로컬 프록시를 바라보면 수집되지 않음 |
| 로컬 수집기를 해당 VPS의 관리 API로 연결 | 관리 API 접근과 기록 설정이 허용되면 수집 가능 |
| 제공자 API·구독 앱을 직접 사용, 해당 CLIProxy를 거치지 않음 | 수집되지 않음. 계정 쿼터 잔여량에는 반영될 수 있음 |

근거는 v8.0.4의 [실행기 사용량 발행](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.4/internal/runtime/executor/helps/usage_helpers.go), [큐 이벤트 발행](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.4/internal/redisqueue/plugin.go), [외부 IP를 포함한 기존 테스트](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.4/internal/redisqueue/plugin_test.go)다. 큐 플러그인은 활성화·기록 설정을 확인하지만 localhost/IP 조건으로 요청을 제외하지 않는다. 기존 테스트는 `client_ip: 192.0.2.10`, `resolved_client_ip: 203.0.113.5`와 완전한 토큰 이벤트를 함께 검증한다.

우리 수집기의 허용 필드 목록에도 호출 위치 필터가 없다. 별도 Python 회귀 테스트에서 로컬 IP와 외부 IP 이벤트가 동일하게 저장되는 것을 확인했다. IP 자체는 SQLite에 저장하지 않는다. 실제 외부 LLM 호출을 발생시키는 운영 테스트는 하지 않았으며, Go 실행 환경이 없어 기존 Go 테스트를 재실행하지 않았다.

집계의 제한은 별도다. 상위 제공자가 토큰을 보고하지 않으면 미측정으로 남는다. 요청/실행기 종류에 따라 보고 지원이 다를 수 있다. 기록이 꺼졌거나 수집기 중단 중 큐 보관 시간이 지나면 누락된다. [큐](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.4/internal/redisqueue/queue.go)의 기본 보관은 60초, 설정 상한은 3600초이며 장기 저장소가 아니다. 다른 큐 소비자·usage 구독자가 이벤트를 가져가면 이 수집기의 기록도 불완전할 수 있다. 일반 로그 파일 유무와 사용량 이벤트 저장은 별도다.

## 공식 제거 이유와 사용자 수요

검색 키워드: `usage`, `usage statistics`, `token`, `analytics`, `persistent`, `removed`, `remote requests`. 공식 프런트엔드와 서버의 issue/PR, 제거 커밋과 관리 API 구현을 확인했다.

- [서버 #3336](https://github.com/router-for-me/CLIProxyAPI/issues/3336): 유지관리자 `luispater`가 내장 통계를 더 이상 제공하지 않으며 CPA Usage Keeper·CLIProxyAPI Usage Dashboard·CPA-Manager 사용을 권장했다.
- [서버 #3048](https://github.com/router-for-me/CLIProxyAPI/issues/3048): 요청별 이력이 메모리에 무제한 누적되는 문제에 대해 유지관리자가 통계 기능 제거를 예고했다. 이는 명시적으로 확인한 운영 부담이다. 모든 제거 동기를 성능 하나로 단정하지 않는다.
- [프런트엔드 제거 커밋](https://github.com/router-for-me/Cli-Proxy-API-Management-Center/commit/632be0bbe02e3b938786ca3128e916b43f7fa8ad): UsagePage·차트·집계 API·상태 저장 코드가 삭제됐다.
- [프런트엔드 #254](https://github.com/router-for-me/Cli-Proxy-API-Management-Center/issues/254), [#270](https://github.com/router-for-me/Cli-Proxy-API-Management-Center/issues/270), [#332](https://github.com/router-for-me/Cli-Proxy-API-Management-Center/issues/332): 모델별·기간별 토큰 통계를 보고 싶다는 수요가 반복된다.
- [프런트엔드 PR #440](https://github.com/router-for-me/Cli-Proxy-API-Management-Center/pull/440): 24시간/7일 통계·토큰 그래프·요청 상세 복원 제안이 제출됐으나 머지되지 않고 닫혔다. 조회한 댓글·리뷰에는 명시적인 거절 이유가 없다.
- [서버 PR #4896](https://github.com/router-for-me/CLIProxyAPI/pull/4896), [#3143](https://github.com/router-for-me/CLIProxyAPI/pull/3143): 관리 통계/영속 저장 관련 열린 제안이 있다. 같은 범위의 새 PR을 바로 만들지 않는다.

수요는 있지만 공식 프로젝트가 내장 통계를 복원하겠다고 약속한 근거는 찾지 못했다. 현재 패치는 로컬 사용을 위한 구현이다. 향후 공식 기여는 특정 외부 도구·루프백 주소를 하드코딩한 페이지를 그대로 제출하기보다, 서버가 선언하는 플러그인 Usage 리소스 또는 선택적인 외부 통계 연결로 제안하는 편이 기존 방향에 맞는다. 이슈·댓글·PR은 아직 게시하지 않았다.

## 검증

공식 테스트 1,465개를 파일별 독립 실행해 통과했고 린트·타입 검사·단일 HTML 빌드도 통과했다. 우리 테스트 28개에서 Origin·키·프록시 불일치 거부, CORS 범위, CSP, 로컬/외부 이벤트 동등 저장과 기존 이력 집계를 확인했다. 실제 관리 화면에서 Usage 연결, 7일 기간·서비스 필터, 테마 전환, 모바일 렌더링을 확인했다. 운영 큐를 테스트로 소비하지 않았다.

pen.dev 문서는 `widget.pen`, 통합 Usage 프레임은 `PBdiO`다. 실제 계정/이력의 검증 캡처는 `.local/`에만 보관한다.
