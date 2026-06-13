# 60. Project Modification Route Findings (Axis ④)

## Test 결과 (2026-06-13)

격리된 4계층 임시 프로젝트(`tmp_test_run/bench_modify`: config → store → service →
cli)에 크로스커팅 수정 프롬프트("빈 제목으로 작업 추가 차단, 계층에 맞는 위치에서
입력 검증 + 사용자 친화적 오류")를 allCode와 codex에 각각 투입.

- **codex** (`exec --sandbox workspace-write`): `service.py` + `cli.py`를 수정해
  서비스 계층 검증 + CLI 오류 처리를 추가. 깔끔한 크로스커팅 변경. EXIT 0.
- **allCode** (`--headless --approval auto --workspace`): **파일 변경 0, EXIT 1**.
  세션 로그상 모델이 `list_tree`(1)·`read_file`(3)만 호출하고 `patch_file`/
  `write_file`를 **한 번도 시도하지 않음**. "Blocked read_file ... a mutation
  request has not produced file-change evidence yet"로 막힌 read를 반복하다 종료.

## 근본 원인

1. **모델 edit-emission 한계 (주요)**: `mutation_action_request` 프롬프트가
   "call patch_file or write_file with the concrete file change"로 명확히
   지시하는데도 wise-lloa-max는 mutation 도구 호출을 emit하지 않고 탐색만 반복.
   codex(gpt-5.5)는 동일 작업에서 정상적으로 edit를 emit. → 벤치마크 격차의
   상당 부분이 **하부 모델 역량**(vLLM wise-lloa-max vs Codex gpt-5.5)이며 harness
   튜닝으로 강제할 수 없음.
2. **게이트가 빈 실패로 hard-block (부차, 개선됨)**: modify phase gate가 inspection
   예산/threshold 소진 시 read를 차단하고, 모델이 mutation을 안 하면 빈
   "요청 실패"로 끝남. 다중 파일 리팩토링에 필요한 탐색 여유가 부족했음.

## 적용한 harness 개선 (regression 없음, 775 passed)

- `round_runner.py`: 기본 inspection 예산 5→7 action / 4→6 round(다중 파일
  리팩토링이 config→store→service→cli를 읽을 여유). mutation-only 조기 잠금 임계
  `mutation_action_requests >= 2`→`>= 4`(계층 이해 전 read 차단 완화).
- `phase_gate.py`: mutation-pending + 예산 여유 시 허용 도구를 `read_file`만이
  아니라 INSPECTION_TOOLS 전체로(navigation 가능). `INSPECTION_TOOLS`에
  `list_tree`·`glob_files` 추가.

이 개선들은 **edit를 emit하는 (더 강한) 모델**이 수정 전 모든 계층을 읽도록 돕는다.
wise-lloa-max의 edit-emission 한계 자체는 harness로 극복 불가.

## 남은 방향 (후속)

- **Graceful degradation**: 모델이 탐색했으나 mutation을 안 하면 빈 실패 대신 구체적
  변경 PLAN/diff 초안을 제시(codex류 "이렇게 바꾸겠다"). 단, 실제 변경 의무를
  가리지 않도록 부분 성공으로 표기.
- 모델 역량 의존도가 높은 축(③ 심층 분석, ④ 수정)은 harness 상한과 모델 상한을
  분리해 평가해야 함. 벤치마크 목표(Codex=gpt-5.5) 대비 격차에는 모델 격차가 포함됨.
