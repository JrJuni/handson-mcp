-- 손코딩 연습 기록·분석 도구 스키마 (3 테이블)
-- type_tags / mistake_tags 는 정규화 대신 JSON 배열로 저장하고,
-- 분석 시 SQLite json_each() 로 풀어서 태그 단위 집계한다.

PRAGMA foreign_keys = ON;

-- 1) problems — 문제 자체 (platform+name 으로 upsert)
CREATE TABLE IF NOT EXISTS problems (
    id          INTEGER PRIMARY KEY,
    platform    TEXT NOT NULL,                  -- leetcode / kaggle / ...
    name        TEXT NOT NULL,
    difficulty  TEXT,                           -- easy / medium / hard / NULL
    type_tags   TEXT NOT NULL DEFAULT '[]',     -- JSON 배열. 예: ["tree","dp"]
    statement   TEXT,                           -- 문제 원문(긴 텍스트)
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (platform, name)
);

-- 2) attempts — 시도들 (problems 에 N:1)
CREATE TABLE IF NOT EXISTS attempts (
    id              INTEGER PRIMARY KEY,
    problem_id      INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    attempt_no      INTEGER NOT NULL,           -- 1, 2, 3... 회차
    with_hint       INTEGER NOT NULL DEFAULT 0, -- 0/1
    answer          TEXT,                       -- 내 답안 (긴 텍스트)
    llm_verdict     TEXT,                       -- pass / fail (host LLM 임시 판정)
    llm_reasoning   TEXT,                       -- LLM 판정 근거 (오판 분석용)
    platform_result TEXT NOT NULL DEFAULT 'pending', -- pass / fail / pending / not_submitted
    mistake_tags    TEXT NOT NULL DEFAULT '[]', -- JSON 배열 (고정 어휘)
    time_sec        INTEGER,                    -- 소요 시간(초, 선택)
    notes           TEXT,                       -- 자유 서술 회고
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (problem_id, attempt_no)
);

CREATE INDEX IF NOT EXISTS idx_attempts_problem ON attempts(problem_id);

-- 3) judge_corrections — LLM 판정 교정 규칙 (압축 메모리 레이어)
CREATE TABLE IF NOT EXISTS judge_corrections (
    id             INTEGER PRIMARY KEY,
    type_tag       TEXT NOT NULL,               -- 단일 태그. 여러 유형이면 여러 행
    correction     TEXT NOT NULL,               -- 압축된 규칙
    evidence_count INTEGER NOT NULL DEFAULT 1,  -- 도출 근거 건수(신뢰도 가중치)
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (type_tag, correction)
);

CREATE INDEX IF NOT EXISTS idx_corrections_tag ON judge_corrections(type_tag);
