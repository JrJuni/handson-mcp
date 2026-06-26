"""엔드투엔드 스모크 테스트: 임시 DB 로 전체 워크플로우 한 바퀴."""
import json
import os
import tempfile

# import 전에 임시 DB 경로 지정
_tmp = tempfile.mkdtemp()
os.environ["HANDSON_DB_PATH"] = os.path.join(_tmp, "test.db")

import server as s  # noqa: E402

print("== 1. record_attempt: 힌트 없이 1차 시도 (LLM은 pass 라 판정) ==")
r1 = s.record_attempt(
    platform="leetcode", name="Validate BST", difficulty="medium",
    answer="def isValidBST(root): ...", llm_verdict="pass",
    type_tags=["tree", "bst", "dfs"], mistake_tags=[],
    llm_reasoning="재귀 구조 맞아 보임", statement="Given root of a binary tree...",
)
print(r1)
assert r1["attempt_no"] == 1

print("\n== 2. update_platform_result: 실제론 fail → 오판 사례 ==")
u1 = s.update_platform_result(platform_result="fail", attempt_id=r1["attempt_id"])
print(u1)
assert u1["misjudged"] is True
assert "tree" in u1["type_tags"]

print("\n== 3. add_correction: 오판에서 규칙 도출 (tree, bst 두 행) ==")
print(s.add_correction("tree", "null root / 단일 노드 경계 검증 자주 누락"))
print(s.add_correction("bst", "inorder 단조증가 위반(중복값 포함) 점검 누락"))
print(s.add_correction("tree", "null root / 단일 노드 경계 검증 자주 누락"))  # 병합→count 2

print("\n== 4. get_corrections: 판정 전 주입용 ==")
corr = s.get_corrections(["tree", "bst", "dfs"])
print(json.dumps(corr, ensure_ascii=False, indent=2))
assert any(c["type_tag"] == "tree" and c["evidence_count"] == 2 for c in corr)

print("\n== 5. record_attempt: 힌트 받고 2차 시도 → pass ==")
r2 = s.record_attempt(
    platform="leetcode", name="Validate BST", answer="fixed null handling",
    llm_verdict="pass", with_hint=True, type_tags=["tree", "bst", "dfs"],
    mistake_tags=["null-handling", "boundary"], platform_result="pass",
)
print(r2)
assert r2["attempt_no"] == 2

# 두 번째 문제 하나 더 (분석 다양성)
s.record_attempt(
    platform="leetcode", name="Two Sum", difficulty="easy",
    answer="hashmap", llm_verdict="pass", type_tags=["array", "hash-table"],
    platform_result="pass",
)

print("\n== 6. analyze ==")
for q in ["overview", "topic_error_rate", "hint_improvement",
          "mistake_frequency", "llm_misjudgment_rate", "misjudgments"]:
    print(f"\n--- {q} ---")
    print(json.dumps(s.analyze(q), ensure_ascii=False, indent=2))

print("\n== 7. 검증: 어휘 밖 태그 거부 ==")
try:
    s.record_attempt(platform="x", name="y", answer="z", type_tags=["bogus-tag"])
    print("FAIL: 거부됐어야 함")
except ValueError as e:
    print("OK rejected:", e)

print("\n=== ALL PASSED ===")
