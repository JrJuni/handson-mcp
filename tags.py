"""고정 태그 어휘(enum) + 검증.

태그 어휘 일관성이 분석 품질을 좌우하므로, DB 가 아니라 코드 상수로 고정한다.
저장 시점에 이 목록 밖의 태그는 거부한다. 새 태그가 필요하면 여기 추가 후 재시작.
"""

# 유형 태그 — LeetCode 공식 태그 중심. 가능하면 플랫폼 공식 태그를 그대로 쓴다.
TYPE_TAGS = frozenset({
    "array", "string", "hash-table", "two-pointers", "sliding-window",
    "binary-search", "stack", "queue", "linked-list",
    "tree", "binary-tree", "bst", "heap", "trie", "union-find",
    "graph", "bfs", "dfs", "backtracking", "topological-sort",
    "dp", "greedy", "divide-and-conquer", "recursion",
    "sorting", "bit-manipulation", "math", "matrix", "simulation",
    "design", "sql", "brute-force",
})

# 실수 태그 — 집계 대상. 자유 서술은 notes/reasoning 으로 분리한다.
MISTAKE_TAGS = frozenset({
    "off-by-one", "null-handling", "edge-case-empty", "boundary",
    "integer-overflow", "wrong-data-structure", "time-complexity",
    "space-complexity", "logic-error", "typo", "incomplete",
    "misread-problem", "infinite-loop", "duplicate-handling",
    "sort-order", "index-error", "uninitialized", "wrong-base-case",
})

VERDICTS = frozenset({"pass", "fail"})
PLATFORM_RESULTS = frozenset({"pass", "fail", "pending", "not_submitted"})


def _validate(values, allowed, label):
    """values 의 모든 항목이 allowed 안에 있는지 확인. 아니면 ValueError."""
    if values is None:
        return []
    if isinstance(values, str):
        raise ValueError(f"{label} must be a list, got a string: {values!r}")
    unknown = [v for v in values if v not in allowed]
    if unknown:
        raise ValueError(
            f"unknown {label}: {unknown}. allowed = {sorted(allowed)}"
        )
    # 중복 제거(순서 유지)
    seen, out = set(), []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def validate_type_tags(values):
    return _validate(values, TYPE_TAGS, "type_tags")


def validate_mistake_tags(values):
    return _validate(values, MISTAKE_TAGS, "mistake_tags")


def validate_verdict(value):
    if value is None:
        return None
    if value not in VERDICTS:
        raise ValueError(f"llm_verdict must be one of {sorted(VERDICTS)}, got {value!r}")
    return value


def validate_platform_result(value):
    if value not in PLATFORM_RESULTS:
        raise ValueError(
            f"platform_result must be one of {sorted(PLATFORM_RESULTS)}, got {value!r}"
        )
    return value
