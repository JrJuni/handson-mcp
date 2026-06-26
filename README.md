# 손코딩 연습 기록·분석 MCP

LeetCode·Kaggle 등에서 푼 문제와 답안을 누적 저장하고 **약한 유형을 분석**하는 개인용 MCP 도구.
부가로 host LLM의 임시 판정과 플랫폼 최종 결과를 비교해 **LLM 오판을 유형별 교정 규칙으로 점진 개선**한다.

> 설계 원칙: 직접 짤 코드는 최소화. MCP 도구는 "저장/조회"만, 판정·태그 추출·규칙 텍스트 생성은 host LLM이 한다.

## 구성
- `schema.sql` — 3 테이블 (problems / attempts / judge_corrections)
- `tags.py` — 고정 태그 어휘(enum) + 검증
- `server.py` — FastMCP 서버, 도구 5개
- `smoke_test.py` — 엔드투엔드 테스트 (`python smoke_test.py`)

## 설치
```bash
pip install -r requirements.txt
```
DB 파일은 기본적으로 `server.py` 옆 `handson.db`에 생성된다. 바꾸려면 환경변수 `HANDSON_DB_PATH` 지정.

## Claude Code / 데스크톱에 등록
`claude_desktop_config.json` (또는 `.mcp.json`)의 `mcpServers`에 추가:
```json
{
  "mcpServers": {
    "handson-coding": {
      "command": "python",
      "args": ["C:/Users/JuniBecky/Downloads/handson-mcp/server.py"],
      "env": { "HANDSON_DB_PATH": "C:/Users/JuniBecky/Downloads/handson-mcp/handson.db" }
    }
  }
}
```

## 도구
| 도구 | 역할 |
|---|---|
| `record_attempt` | 문제 upsert(platform+name) + 시도 1건 저장. attempt_no 자동 부여 |
| `update_platform_result` | 플랫폼 최종 결과 반영. 오판이면 `misjudged=True` + type_tags 반환 |
| `get_corrections` | type_tags 매칭 교정 규칙을 evidence_count 순으로 조회 (판정 전 주입) |
| `add_correction` | 오판에서 도출한 규칙 추가/병합 (evidence_count 증가) |
| `analyze` | 사전 정의 분석 쿼리 실행 |

`analyze` 쿼리: `overview`, `topic_error_rate`, `hint_improvement`, `mistake_frequency`,
`llm_misjudgment_rate`, `time_trend`, `misjudgments`

## 워크플로우 (host LLM 대화 안에서)
1. 문제 + 초안 답안 입력
2. host LLM이 `get_corrections(type_tags)`로 교정 규칙을 읽고 → 임시 판정(아래 프롬프트)
3. `record_attempt(..., llm_verdict, platform_result="pending")`
4. 플랫폼에 실제 제출 → 결과 회수
5. `update_platform_result(...)` → `misjudged=True`면 host가 규칙 도출해 `add_correction`
6. (오답 시) 힌트 → 다시 풂 → `record_attempt(with_hint=True)` → 재검증
7. `analyze`로 누적 분석

## 판정 프롬프트 템플릿 (host LLM 시스템 프롬프트 골격)
```
[역할] 너는 코테 답안 채점 보조다. 코드를 읽고 정답/오답을 임시 판정한다.

[참고: 이 유형에서 과거 자주 놓친 점]   ← get_corrections(type_tags) 결과 주입
{corrections}

[판정 기준]
- 통과 케이스를 다 돌릴 수 없으므로 논리적 추론으로 판정
- 엣지케이스(빈 입력, 경계값, null) 명시적으로 점검

[출력: JSON only]
{
  "verdict": "pass" | "fail",
  "type_tags": [고정 목록에서 선택],
  "mistake_tags": [고정 목록에서 선택],
  "reasoning": "간단 근거"
}
```
고정 태그 어휘는 `tags.py`의 `TYPE_TAGS` / `MISTAKE_TAGS` 참조.

## 한계
- LLM 판정 ≠ 플랫폼 채점. 플랫폼 최종 결과가 ground truth, LLM 판정은 보조.
- 교정 규칙은 오판을 다 못 막는다. 기대치는 "유형 안에서의 점진 개선".
- 유형 분류기도 틀린다. 가능하면 플랫폼 공식 태그 사용.
