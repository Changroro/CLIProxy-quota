# 공식 관리 화면의 미니멀 테마

GTK 위젯은 CLIProxy-quota를 사용하고 기본 대시보드는 공식 Management Center를 사용한다. `#/usage`에는 기존 토큰 이력 화면을 연결하는 별도 패치를 적용했다. [Usage 통합과 수집 범위](USAGE_INTEGRATION.md)를 참고한다. 공식 메뉴·집계·OAuth·쿼터·설정·로그 기능은 유지하며 SCSS만 추가한다. 테마 소스는 `management-theme/`에 분리한다.

## 빌드

Git, Bun 1.3.14, uv가 필요하다.

```bash
uv run --no-project --python /usr/bin/python3 python scripts/build_management.py
```

기준 소스: [공식 Management Center a7ec312](https://github.com/router-for-me/Cli-Proxy-API-Management-Center/tree/a7ec312fbbb0a13f3a580ee0c7e29228a07c8867). 소스는 `.local/management-center`, 결과는 `.local/management.html`이다. 다른 버전의 소스에서 빌드하면 오류로 중단한다. 버전을 올릴 때 대상 SCSS와 실제 화면을 다시 검증한다.

`minimal.scss`는 공통 색상·글꼴·탐색 UI, `dashboard.scss`는 공식 대시보드의 간격·크기·표면, `login.scss`는 로그인 화면의 표면을 담당한다. SCSS 테마는 API·라우트·데이터 저장 코드를 수정하지 않는다. 별도 `usage.patch`는 보호된 Usage 라우트와 로컬 수집기 인증 연결을 추가하며, 프록시의 집계·저장 코드는 수정하지 않는다. 공식 MIT 고지는 `management-theme/UPSTREAM_LICENSE`에 보존한다. 공식 언어와 테마 선택기는 그대로 사용한다. 공식 화면의 한국어 번역은 이 테마에 포함되지 않는다. GTK 위젯과 별도 토큰 이력 화면은 한글·영어를 지원한다.

라이트는 흰색과 회색, 다크는 `#1c1c1e`와 `#242426`을 사용한다. 잔여량/요청 상태는 초록 `#22c55e`, 노랑 `#facc15`, 빨강 `#ef4444`이다. 기본은 공식 시스템 테마를 유지한다. 기존 승인 시안과 Refero의 평평한 흰색 표면·작은 일반 글꼴을 참고한다. 배경 그리드·장식용 파형·큰 브랜드 문구를 제거하고 숫자와 실제 그래프를 유지한다.

pen.dev 문서는 `widget.pen`, 공식 화면 테마 라이트 프레임은 `zv4J9`, 다크 프레임은 `BajSm`이다. 기존 자체 대시보드 시안은 비교용으로 보존한다.

## 설치와 업데이트

결과 HTML을 CLIProxyAPI의 관리 화면 정적 경로에 `management.html`로 설치한다. 로컬 Docker의 경로는 `/CLIProxyAPI/static/management.html`이다. 기존 파일을 먼저 백업한다.

공식 자동 업데이트는 이 파일을 덮어쓰므로 `management.disable-auto-update-panel: true`로 설정하고, 공식 새 버전을 검토한 뒤 테마를 다시 빌드해 설치한다. Docker 컨테이너 재생성 시 정적 파일도 재설치해야 한다. 자동 업데이트를 다시 켜면 공식 원본으로 돌아간다.

관리 화면은 기존 관리 키로 직접 로그인한다. 위젯은 URL로 관리 키나 로컬 수집기 토큰을 전달하지 않는다.

```bash
./bin/cli-proxy-quota open
./bin/cli-proxy-quota open-history
```

`open`은 공식 관리 화면, `open-history`는 기존 수집기의 토큰 이력을 연다. `dashboard --no-open`은 기존 공용 수집기를 계속 실행한다. SQLite 이력은 삭제하지 않는다.

## 공식 통계 기능 재확인

2026-10-01 최신 공식 v8 소스의 라우트에는 장기간 토큰 이력 분석 페이지가 없다. 현재 대시보드 요청 그래프는 10분 단위 20개 구간(약 200분)이며 쿼터 타임라인은 사용량 이력이 아니라 한도 초기화 일정이다. 사용량 큐는 장기 저장소가 아니다.

그러나 **과거 공식 화면에는 해당 통계가 있었다.** [제거 직전 UsagePage](https://github.com/router-for-me/Cli-Proxy-API-Management-Center/blob/7d3c57092b6fb61fcde3f473bbc7115fcd2117ce/src/pages/UsagePage.tsx)는 전체·7시간·24시간·7일 필터, 시간/일 단위 요청·토큰 차트, 모델별 통계·비용 추이·토큰 분포와 가져오기/내보내기를 제공했다. [2026-05-01 제거 커밋](https://github.com/router-for-me/Cli-Proxy-API-Management-Center/commit/632be0bbe02e3b938786ca3128e916b43f7fa8ad)에서 관련 페이지·API·저장 상태·차트가 제거됐다.

그 구형 페이지는 `/usage`·`/usage/export`·`/usage/import` API에 의존한다. 현재 v8에서 테마만 적용한다고 복구되지 않는다. 오래된 공식 UI로 되돌려 장기 기록 문제를 해결하려 하지 않는다. 현재 수집기·SQLite와 별도 이력 화면을 보존한다. 플러그인은 자체 통계 페이지를 제공할 수 있지만 공식 기본 기능과 구분한다.

## 검증 기록 (2026-10-01)

공식 원본 `bun run verify`의 전체 테스트는 i18n 전역 상태가 파일 간 공유되어 2개가 실패한다. 테마 없이도 같은 두 실패를 재현했다. `bun test --isolate`는 각 파일의 전역 객체를 분리해 모든 1,465개 테스트와 assertion을 실행하며 전부 통과했다. 빌드 스크립트는 이 방식과 공식 lint·TypeScript/Vite 빌드를 실행한다. 테스트를 제외하거나 assertion을 변경하지 않는다.

공식 관리 URL에서 라이트·다크, 360px·1280px, 쿼터·설정·로그 이동을 확인했다. 실제 계정/설정이 포함된 검증 캡처는 `.local/`에만 보관하며 공개 문서에 넣지 않는다. 관리 HTML은 브라우저 캐시와 구분하기 위해 위젯 링크에 `?theme=cli-proxy-quota`를 붙인다. 원본을 이미 열어 둔 탭은 새 링크로 열거나 강력 새로고침한다.
