# 영상 제작 근거

승인된 미니멀 UI 모션. 한국어·영어 각 30초, 1920×1080, 30fps. 무음이며 Canvas 코드와 저장소의 서비스 아이콘으로 화면을 구성한다. 운영 데이터, 메일, 토큰, 키, 가상 사용량 수치, 초기화 날짜를 사용하지 않는다. 화면의 `—`는 값을 생략했다는 표현이다. 차트는 축과 수치를 갖지 않는 추상 영역 표시이며 관측값을 나타내지 않는다.

| 기능 사실 | 저장소 근거 |
| --- | --- |
| Linux 네이티브 GTK 위젯 | `cli_proxy_quota/widget.py`: `QuotaWindow`, `UsageApplication`; `README.ko.md` |
| 기존 CLIProxyAPI 서버에 연결 | `cli_proxy_quota/configuration.py`: `load_settings`; `cli_proxy_quota/client.py` |
| 위젯 기본 폭 260px | `cli_proxy_quota/widget.py`: `set_default_size(260, -1)` — 영상 유일한 수치 |
| Codex·Claude·OpenRouter 서비스 구분 | `cli_proxy_quota/widget.py`: `render_cards`; `cli_proxy_quota/client.py`: 보고서 수집 |
| API 플랜 배지와 잔여량 표시 | `cli_proxy_quota/widget.py`: `PLAN_LABELS`, 계정 카드·메트릭 렌더 |
| 계정 아이콘의 상세 팝오버 | `cli_proxy_quota/widget.py`: 계정 상세 구성, 다음·직전 초기화 정보 |
| 계정 별칭 편집 | `cli_proxy_quota/widget.py`: `edit_alias`, `save_aliases` |
| Codex 계정 우선순위 편집·저장·취소 | `cli_proxy_quota/widget.py`: 계정 순서 편집; `client.py`: 우선순위 저장. 저장은 fill-first 라우팅 필요 |
| 시스템·라이트·다크 테마 | `cli_proxy_quota/widget.py`: `choose_theme`, `apply_theme`; `configuration.py`: `save_theme` |
| 한국어·영어 UI | `cli_proxy_quota/i18n.py`, `translations.json`; `configuration.py`: 언어 설정 |
| 대시보드 필터·요약·시간별/계정별 그래프 영역 | `cli_proxy_quota/dashboard.py`, `ledger.py`, `web/` 구현. HTTP 인증·Origin·필터·집계 테스트와 실제 브라우저의 필터·그래프·언어·테마·모바일 검증 완료 |

색상은 `widget.py`의 `LIGHT_CSS`, `DARK_PALETTE`, `BAR_COLORS`에서 가져왔다. 영상의 위젯은 가독성을 위해 확대해 그리며 실제 Codex/OpenAI·Claude·OpenRouter 아이콘을 사용한다. Codex·Claude는 GTK와 같은 단색 심볼로 표시하고 OpenRouter는 원본 색상과 비율을 유지한다. 개인정보 없는 개념 표현으로 실제 화면을 녹화한 것이 아니다.

폰트: [Pretendard](https://github.com/orioncactus/pretendard), SIL Open Font License (`assets/fonts/OFL.txt`). 코드 렌더 엔진: 승인된 code-video 스킬의 `kit.js`, `render.mjs`. 특정 외부 영상의 스타일을 차용하지 않았다.

재현:

```bash
cd docs/video
npm ci
QUERY=lang=ko CRF=25 node render.mjs video cliproxy-quota-ko.mp4
QUERY=lang=en CRF=25 node render.mjs video cliproxy-quota-en.mp4
QUERY=lang=ko node render.mjs stills 2 8.5 11.8 15.8 21 28
```

필수 도구: Node.js/npm, Google Chrome, ffmpeg(libx264), uv. `node_modules/`, `stills/`는 공개 결과에서 제외한다.

최종 검증: 두 MP4 모두 H.264, 1920×1080, 30fps, 30초이며 한국어·영어 장면의 스틸을 확인했다. 운영 수집 실행 여부를 주장하지 않는다.

서비스 아이콘 출처와 상표권 고지: [프로젝트 브랜드 에셋](../../assets/README.md), [CLIProxyAPI MIT 고지](../../assets/CLIProxyAPI-LICENSE), [EasyCLIProxyAPI MIT 고지](../../assets/CLIProxy-LICENSE). 상표권은 각 소유자에게 있으며 공식 인증·제휴를 의미하지 않는다. 복사된 파일은 `assets/services/`에 있다.
