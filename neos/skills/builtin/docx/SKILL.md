---
name: docx
type: document
version: 1.0.0
description: Microsoft Word 문서 읽기, 생성, 편집
capabilities:
  - document_reading
  - document_creation
  - document_editing
  - text_extraction
dependencies:
  - python-docx>=1.1.0
---

# DOCX Skill

## Description
Microsoft Word 문서(.docx)를 읽고, 생성하고, 편집하는 스킬입니다.

## Capabilities
- DOCX 파일 읽기 및 텍스트 추출
- 새로운 DOCX 문서 생성
- 기존 문서에 내용 추가
- 문서 스타일 및 서식 적용
- 표, 이미지 등 삽입

## Usage
이 스킬은 python-docx 라이브러리를 사용하여 Word 문서를 처리합니다.

### Parameters
- `action`: 수행할 작업 ("read", "create", "update")
- `file_path`: 파일 경로
- `content`: 작성할 내용 (create/update 시)
- `options`: 추가 옵션 (스타일, 서식 등)

### Example
```python
# 문서 읽기
params = {
    "action": "read",
    "file_path": "/path/to/document.docx"
}

# 문서 생성
params = {
    "action": "create",
    "file_path": "/path/to/new_document.docx",
    "content": "Hello, World!",
    "options": {"heading": "Introduction"}
}
```

## Requirements
- python-docx 패키지 설치

## Version
1.0.0
