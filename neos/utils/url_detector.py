"""URL 감지 유틸리티"""

import re
from typing import List


def extract_urls(text: str) -> List[str]:
    """텍스트에서 URL을 추출합니다.

    Args:
        text: URL을 추출할 텍스트

    Returns:
        추출된 URL 리스트
    """
    # URL 패턴 정규식
    # http:// 또는 https:// 로 시작하는 URL
    # www. 로 시작하는 URL
    # 도메인.확장자 형태의 URL
    url_pattern = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        r'|www\.(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        r'|(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,6}(?:/[^\s]*)?'
    )

    urls = url_pattern.findall(text)

    # www로 시작하는 URL은 http:// 추가
    normalized_urls = []
    for url in urls:
        # URL 끝의 구두점 제거 (쉼표, 마침표, 괄호 등)
        url = url.rstrip(',.!?;:\'"()[]{}')

        if url.startswith('www.'):
            normalized_urls.append(f'https://{url}')
        elif not url.startswith(('http://', 'https://')):
            # 도메인만 있는 경우 https:// 추가
            if '.' in url:
                normalized_urls.append(f'https://{url}')
        else:
            normalized_urls.append(url)

    # 중복 제거
    return list(set(normalized_urls))


def has_urls(text: str) -> bool:
    """텍스트에 URL이 포함되어 있는지 확인합니다.

    Args:
        text: 확인할 텍스트

    Returns:
        URL 포함 여부
    """
    return len(extract_urls(text)) > 0


def is_valid_url(url: str) -> bool:
    """URL이 유효한지 확인합니다.

    Args:
        url: 확인할 URL

    Returns:
        유효성 여부
    """
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # or IP
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)

    return url_pattern.match(url) is not None
