"""손코딩 연습 기록·분석 MCP 서버 (Python FastMCP).

설계 원칙: MCP 도구는 "멍청한 저장/조회"로만 둔다.
판정(llm_verdict)·교정 규칙 텍스트 생성·태그 추출은 모두 host LLM 의 일이고,
이 서버는 그 결과를 저장하고, 분석 쿼리로 다시 노출만 한다.
"""

import json
import os
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import tags as T

DB_PATH = Path(os.environ.get("HANDSON_DB_PATH", Path(__file__).parent / "handson.db"))
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

mcp = FastMCP("handson-coding")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _init_db():
    with _connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def _rows(cur):
    return [dict(r) for r in cur.fetchall()]


_init_db()


# ---------------------------------------------------------------------------
# 1) record_attempt — 문제 upsert + 시도 저장
# ---------------------------------------------------------------------------
@mcp.tool()
def record_attempt(
    platform: str,
    name: str,
    answer: str,
    llm_verdict: str | None = None,
    type_tags: list[str] | None = None,
    mistake_tags: list[str] | None = None,
    difficulty: str | None = None,
    statement: str | None = None,
    with_hint: bool = False,
    platform_result: str = "pending",
    llm_reasoning: str | None = None,
    time_sec: int | None = None,
    notes: str | None = None,
) -> dict:
    """문제를 upsert(platform+name 기준)하고 시도 1건을 저장한다.

    attempt_no 는 해당 문제의 기존 최대값+1 로 자동 부여된다.
    type_tags / mistake_tags 는 고정 어휘(tags.py)로 검증된다.
    힌트 전/후를 각각 별도 attempt 로 기록하면 "힌트 의존 유형"이 드러난다.
    """
    type_tags = T.validate_type_tags(type_tags)
    mistake_tags = T.validate_mistake_tags(mistake_tags)
    llm_verdict = T.validate_verdict(llm_verdict)
    platform_result = T.validate_platform_result(platform_result)

    with _connect() as conn:
        # problem upsert: 새로 만들거나, 기존 행의 메타데이터를 채워준다.
        conn.execute(
            """
            INSERT INTO problems (platform, name, difficulty, type_tags, statement)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(platform, name) DO UPDATE SET
                difficulty = COALESCE(excluded.difficulty, problems.difficulty),
                type_tags  = CASE WHEN excluded.type_tags = '[]'
                                  THEN problems.type_tags ELSE excluded.type_tags END,
                statement  = COALESCE(excluded.statement, problems.statement)
            """,
            (platform, name, difficulty, json.dumps(type_tags), statement),
        )
        problem_id = conn.execute(
            "SELECT id FROM problems WHERE platform=? AND name=?", (platform, name)
        ).fetchone()["id"]

        next_no = conn.execute(
            "SELECT COALESCE(MAX(attempt_no), 0) + 1 AS n FROM attempts WHERE problem_id=?",
            (problem_id,),
        ).fetchone()["n"]

        cur = conn.execute(
            """
            INSERT INTO attempts
              (problem_id, attempt_no, with_hint, answer, llm_verdict, llm_reasoning,
               platform_result, mistake_tags, time_sec, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                problem_id, next_no, int(with_hint), answer, llm_verdict, llm_reasoning,
                platform_result, json.dumps(mistake_tags), time_sec, notes,
            ),
        )
        return {
            "problem_id": problem_id,
            "attempt_id": cur.lastrowid,
            "attempt_no": next_no,
            "platform_result": platform_result,
        }


# ---------------------------------------------------------------------------
# 2) update_platform_result — 플랫폼 최종 결과 반영
# ---------------------------------------------------------------------------
@mcp.tool()
def update_platform_result(
    platform_result: str,
    attempt_id: int | None = None,
    problem_id: int | None = None,
) -> dict:
    """플랫폼 최종 채점 결과를 반영한다.

    attempt_id 를 주면 그 시도를, 없으면 problem_id 의 가장 최근 시도를 갱신한다.
    오판 사례(llm_verdict='pass' AND platform_result='fail')면 misjudged=True 와
    함께 해당 문제의 type_tags 를 돌려준다 → host 가 add_correction 호출 여부를 판단.
    (규칙 텍스트 생성은 LLM 일이므로 서버는 자동 생성하지 않는다.)
    """
    platform_result = T.validate_platform_result(platform_result)

    with _connect() as conn:
        if attempt_id is None:
            if problem_id is None:
                raise ValueError("attempt_id 또는 problem_id 중 하나는 필요합니다.")
            row = conn.execute(
                "SELECT id FROM attempts WHERE problem_id=? ORDER BY attempt_no DESC LIMIT 1",
                (problem_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"problem_id={problem_id} 에 시도가 없습니다.")
            attempt_id = row["id"]

        conn.execute(
            "UPDATE attempts SET platform_result=? WHERE id=?",
            (platform_result, attempt_id),
        )
        a = conn.execute(
            """
            SELECT a.id, a.problem_id, a.attempt_no, a.llm_verdict, a.platform_result,
                   p.type_tags
            FROM attempts a JOIN problems p ON p.id = a.problem_id
            WHERE a.id = ?
            """,
            (attempt_id,),
        ).fetchone()
        if a is None:
            raise ValueError(f"attempt_id={attempt_id} 를 찾을 수 없습니다.")

        misjudged = a["llm_verdict"] == "pass" and a["platform_result"] == "fail"
        return {
            "attempt_id": a["id"],
            "problem_id": a["problem_id"],
            "attempt_no": a["attempt_no"],
            "platform_result": a["platform_result"],
            "misjudged": misjudged,
            "type_tags": json.loads(a["type_tags"]),
        }


# ---------------------------------------------------------------------------
# 3) get_corrections — 판정 전 주입용 교정 규칙 조회
# ---------------------------------------------------------------------------
@mcp.tool()
def get_corrections(type_tags: list[str], top_n: int = 5) -> list[dict]:
    """주어진 type_tags 에 해당하는 교정 규칙을 evidence_count 높은 순으로 조회한다.

    판정 프롬프트에 주입할 용도. top_n 으로 프롬프트 길이를 통제한다.
    """
    type_tags = T.validate_type_tags(type_tags)
    if not type_tags:
        return []
    placeholders = ",".join("?" * len(type_tags))
    with _connect() as conn:
        cur = conn.execute(
            f"""
            SELECT id, type_tag, correction, evidence_count, updated_at
            FROM judge_corrections
            WHERE type_tag IN ({placeholders})
            ORDER BY evidence_count DESC, updated_at DESC
            LIMIT ?
            """,
            (*type_tags, top_n),
        )
        return _rows(cur)


# ---------------------------------------------------------------------------
# 4) add_correction — 오판 사례에서 도출한 규칙 추가/병합
# ---------------------------------------------------------------------------
@mcp.tool()
def add_correction(
    type_tag: str,
    correction: str | None = None,
    correction_id: int | None = None,
    evidence_delta: int = 1,
) -> dict:
    """교정 규칙을 추가하거나 기존 규칙의 evidence_count 를 올린다.

    - correction_id 를 주면: 그 규칙의 evidence_count 를 evidence_delta 만큼 증가.
    - correction(텍스트)만 주면: (type_tag, correction) 이 이미 있으면 카운트 증가,
      없으면 새 규칙 삽입.
    병합 판단(비슷한 규칙인지)은 host 가 먼저 get_corrections 로 읽고 결정한다.
    """
    if type_tag not in T.TYPE_TAGS:
        raise ValueError(f"unknown type_tag: {type_tag!r}. allowed = {sorted(T.TYPE_TAGS)}")

    with _connect() as conn:
        if correction_id is not None:
            cur = conn.execute(
                """
                UPDATE judge_corrections
                SET evidence_count = evidence_count + ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (evidence_delta, correction_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"correction_id={correction_id} 를 찾을 수 없습니다.")
            row = conn.execute(
                "SELECT * FROM judge_corrections WHERE id=?", (correction_id,)
            ).fetchone()
            return {"merged": True, **dict(row)}

        if not correction:
            raise ValueError("correction 텍스트 또는 correction_id 중 하나는 필요합니다.")

        # (type_tag, correction) UNIQUE → 충돌 시 카운트 증가
        conn.execute(
            """
            INSERT INTO judge_corrections (type_tag, correction, evidence_count)
            VALUES (?, ?, ?)
            ON CONFLICT(type_tag, correction) DO UPDATE SET
                evidence_count = judge_corrections.evidence_count + excluded.evidence_count,
                updated_at = datetime('now')
            """,
            (type_tag, correction, evidence_delta),
        )
        row = conn.execute(
            "SELECT * FROM judge_corrections WHERE type_tag=? AND correction=?",
            (type_tag, correction),
        ).fetchone()
        merged = row["evidence_count"] > evidence_delta
        return {"merged": merged, **dict(row)}


# ---------------------------------------------------------------------------
# 5) analyze — 사전 정의 분석 쿼리
# ---------------------------------------------------------------------------
_ANALYSES = {
    # 토픽별 오답률 (못하는 유형부터)
    "topic_error_rate": """
        SELECT t.value AS tag,
               SUM(a.platform_result='fail') AS fails,
               SUM(a.platform_result IN ('pass','fail')) AS graded,
               ROUND(1.0*SUM(a.platform_result='fail')
                     / NULLIF(SUM(a.platform_result IN ('pass','fail')),0), 3) AS error_rate
        FROM attempts a
        JOIN problems p ON p.id = a.problem_id
        JOIN json_each(p.type_tags) t
        GROUP BY t.value
        HAVING graded > 0
        ORDER BY error_rate DESC, graded DESC
    """,
    # 힌트 전 vs 후 정답률 → 힌트 의존도
    "hint_improvement": """
        SELECT CASE with_hint WHEN 1 THEN 'with_hint' ELSE 'no_hint' END AS bucket,
               SUM(platform_result='pass') AS passes,
               SUM(platform_result IN ('pass','fail')) AS graded,
               ROUND(1.0*SUM(platform_result='pass')
                     / NULLIF(SUM(platform_result IN ('pass','fail')),0), 3) AS pass_rate
        FROM attempts
        GROUP BY with_hint
    """,
    # 자주 등장하는 실수 태그
    "mistake_frequency": """
        SELECT m.value AS mistake, COUNT(*) AS cnt
        FROM attempts a
        JOIN json_each(a.mistake_tags) m
        GROUP BY m.value
        ORDER BY cnt DESC
    """,
    # 유형별 LLM 오판율 (llm_verdict != platform_result)
    "llm_misjudgment_rate": """
        SELECT t.value AS tag,
               SUM(a.llm_verdict != a.platform_result) AS misjudged,
               COUNT(*) AS graded,
               ROUND(1.0*SUM(a.llm_verdict != a.platform_result) / COUNT(*), 3) AS misjudge_rate
        FROM attempts a
        JOIN problems p ON p.id = a.problem_id
        JOIN json_each(p.type_tags) t
        WHERE a.platform_result IN ('pass','fail') AND a.llm_verdict IS NOT NULL
        GROUP BY t.value
        ORDER BY misjudge_rate DESC, graded DESC
    """,
    # 날짜별 정답률 추이 → 실력 향상 여부
    "time_trend": """
        SELECT date(created_at) AS day,
               SUM(platform_result='pass') AS passes,
               SUM(platform_result IN ('pass','fail')) AS graded,
               ROUND(1.0*SUM(platform_result='pass')
                     / NULLIF(SUM(platform_result IN ('pass','fail')),0), 3) AS pass_rate
        FROM attempts
        GROUP BY date(created_at)
        ORDER BY day
    """,
    # 오판 사례 목록 (llm_verdict='pass' AND platform_result='fail')
    "misjudgments": """
        SELECT a.id AS attempt_id, p.platform, p.name, p.type_tags,
               a.attempt_no, a.with_hint, a.mistake_tags, a.llm_reasoning, a.created_at
        FROM attempts a
        JOIN problems p ON p.id = a.problem_id
        WHERE a.llm_verdict='pass' AND a.platform_result='fail'
        ORDER BY a.created_at DESC
    """,
    # 전체 요약
    "overview": """
        SELECT
          (SELECT COUNT(*) FROM problems) AS problems,
          (SELECT COUNT(*) FROM attempts) AS attempts,
          (SELECT COUNT(*) FROM attempts WHERE platform_result='pending') AS pending,
          (SELECT COUNT(*) FROM attempts WHERE platform_result='pass') AS passes,
          (SELECT COUNT(*) FROM attempts WHERE platform_result='fail') AS fails,
          (SELECT COUNT(*) FROM judge_corrections) AS corrections
    """,
}


@mcp.tool()
def analyze(query: str) -> list[dict]:
    """사전 정의 분석 쿼리를 실행한다.

    query 후보: topic_error_rate, hint_improvement, mistake_frequency,
    llm_misjudgment_rate, time_trend, misjudgments, overview
    """
    if query not in _ANALYSES:
        raise ValueError(f"unknown query: {query!r}. available = {sorted(_ANALYSES)}")
    with _connect() as conn:
        return _rows(conn.execute(_ANALYSES[query]))


if __name__ == "__main__":
    mcp.run()
