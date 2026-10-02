-- 사용자 승인 규칙 allow/require/block (로드맵 트랙 Q2, 2026-10-01).
-- 설계: docs/Q2_Q4B_RULES_CHANNEL_TRIGGERS_DESIGN_261001.md §2
--
-- 규칙은 사용자의 것이다 -- 키는 user_id. 상시 에이전트의 태스크도 소유자의 규칙을 쓴다.
-- 평가 순서는 코드가 고정한다(neos/coding/domain/approvals.py `_evaluate_approval`):
--   USER_ONLY > 기본 DENY > 사용자 block > 보호 파일 REQUIRE > 사용자 require
--   > 운영자 allow > 사용자 allow(위험 등급 기본 REQUIRE 만 바꾼다) > 기본값
-- argv_prefix 는 execute.v1 에만 -- 비어 있으면 도구 전체다.
CREATE TABLE IF NOT EXISTS user_approval_rules (
    rule_id     VARCHAR(64)  PRIMARY KEY,                       -- 'ur_' + hex
    user_id     VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    effect      VARCHAR(16)  NOT NULL CHECK (effect IN ('allow', 'require', 'block')),
    tool        VARCHAR(128) NOT NULL CHECK (btrim(tool) <> ''),
    argv_prefix JSONB        NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(argv_prefix) = 'array'),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 같은 규칙은 하나. 효과가 다르면 다른 규칙이다(block 과 allow 가 함께 있으면 block 이 이긴다).
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_approval_rules_rule
    ON user_approval_rules(user_id, effect, tool, argv_prefix);
