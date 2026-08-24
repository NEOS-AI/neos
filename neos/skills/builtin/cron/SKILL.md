---
name: cron
type: custom
version: 1.0.0
description: 사용자 반복 태스크를 자연어로 스케줄 등록
capabilities:
  - schedule_registration
  - natural_language_cron
  - recurring_task
dependencies: []
allowed_tools: ""
---

# Cron Skill

## Description
사용자의 반복 태스크를 스케줄로 등록합니다. 자연어 표현("매일 아침 9시")을 cron
표현식으로 파싱하며, `cron_expression` 을 직접 넘기면 파싱을 건너뜁니다.

> **`type: custom` 인 이유.** 이 스킬은 검색도 문서 생성도 아니다. 유효 type 목록
> (`metadata_parser.py`)에 `automation` 이 없고, `custom` 이 정확히 "기존 분류에
> 맞지 않는 것" 을 위해 존재하는 값이다. 새 enum 값을 더하면 `SkillType` 과
> `valid_types` 두 곳을 함께 고쳐야 하고, 한쪽만 고치면 `SkillType(...)` 이
> `ValueError` 를 내 **그 스킬 하나가 discovery 전체를 멈춘다**.

## Capabilities
- 자연어 스케줄 표현 파싱
- cron 표현식 직접 지정
- 타임존 지정
- 채널별 전달 대상 지정

## Usage

### Parameters
- `query`: 스케줄 요청 자연어 (**필수**)
- `user_id`: 사용자 식별자 (**필수**)
- `channel_type`: 전달 채널 (선택, 기본값 `"api"`)
- `channel_id`: 채널 식별자 (선택)
- `timezone`: 타임존 (선택, 기본값 `"UTC"`)
- `cron_expression`: cron 표현식 직접 지정 (선택 — 주면 자연어 파싱을 건너뛴다)

`query` 와 `user_id` 가 없으면 `SkillResult(success=False)` 로 거절한다.

### Example

```python
params = {
    "query": "매일 아침 9시에 어제 뉴스 요약해줘",
    "user_id": "u-123",
    "timezone": "Asia/Seoul",
}
result = await skill_manager.execute_skill("cron", params)
```

## Requirements
- 환경 변수 없음
- 스케줄 실행은 Celery Beat 폴러가 담당한다 (`neos/tasks/scheduled_task_runner.py`)

## Version
1.0.0
