---
name: pdf
type: document
version: 1.0.0
description: PDF 문서 읽기, 텍스트 추출, 생성
capabilities:
  - document_reading
  - text_extraction
  - pdf_parsing
  - document_creation
dependencies:
  - PyPDF2>=3.0.0
  - reportlab>=3.6.0
---

# PDF Skill

## Description
PDF 문서를 읽고, 텍스트를 추출하고, 새로운 PDF를 생성하는 스킬입니다.

## Capabilities
- PDF 파일 읽기 및 텍스트 추출
- 페이지별 텍스트 추출
- PDF 메타데이터 추출
- 간단한 PDF 생성
- PDF to Text 변환

## Usage
이 스킬은 PyPDF2 및 reportlab 라이브러리를 사용하여 PDF를 처리합니다.

### Parameters
- `action`: 수행할 작업 ("read", "extract_text", "create")
- `file_path`: 파일 경로
- `page_numbers`: 추출할 페이지 번호 목록 (선택사항)
- `content`: 생성할 PDF 내용 (create 시)

### Example
```python
# PDF 텍스트 추출
params = {
    "action": "extract_text",
    "file_path": "/path/to/document.pdf",
    "page_numbers": [0, 1, 2]  # 첫 3페이지
}

# PDF 생성
params = {
    "action": "create",
    "file_path": "/path/to/new_document.pdf",
    "content": "Hello, PDF World!"
}
```

## Requirements
- PyPDF2 패키지
- reportlab 패키지 (PDF 생성용)

## Version
1.0.0
