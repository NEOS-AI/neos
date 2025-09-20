"""콘텐츠 처리 유틸리티"""

from typing import Dict, Any, List
from urllib.parse import urlparse


class ContentProcessor:
    """콘텐츠 처리 및 포맷팅 유틸리티"""

    def __init__(self):
        self.artifacts_to_remove = [
            '*My Menu 닫기*',
            '본문 바로가기',
            '**본문 폰트 크기 조정**',
            'blog.naver',
            '.com',
            '>>>',
            '>>',
            '* *',
            '>'
        ]

    def categorize_results_by_topic(self, results: List[Any]) -> Dict[str, List[Any]]:
        """주제별 결과 분류"""
        categories = {
            'nvidia': [],
            'meta': [],
            'alphabet': [],
            'general': []
        }

        seen_content = set()

        for result in results:
            title = getattr(result, 'title', '').lower()
            content = getattr(result, 'content', '').lower()
            combined_text = title + ' ' + content

            # 중복 제거를 위한 콘텐츠 해시
            content_hash = hash(title + content[:200])
            if content_hash in seen_content:
                continue
            seen_content.add(content_hash)

            # 키워드 기반 분류
            if any(keyword in combined_text for keyword in ['엔비디아', 'nvidia', 'nvda']):
                categories['nvidia'].append(result)
            elif any(keyword in combined_text for keyword in ['메타', 'meta', '페이스북', 'facebook']):
                categories['meta'].append(result)
            elif any(keyword in combined_text for keyword in ['알파벳', 'alphabet', '구글', 'google', 'googl']):
                categories['alphabet'].append(result)
            else:
                categories['general'].append(result)

        # 각 카테고리를 점수순으로 정렬
        for category in categories:
            categories[category] = sorted(
                categories[category],
                key=lambda x: getattr(x, 'score', 0),
                reverse=True
            )

        return categories

    def process_content_for_display(self, content: str, max_length: int = 400) -> str:
        """표시용 콘텐츠 처리"""
        if not content or content.strip() == "":
            return "내용이 없습니다."

        # 콘텐츠 정리
        content = content.strip()
        content = ' '.join(content.split())  # 과도한 공백 제거

        # 웹 아티팩트 제거
        for artifact in self.artifacts_to_remove:
            content = content.replace(artifact, '').strip()

        # 길이가 충분히 짧으면 그대로 반환
        if len(content) <= max_length:
            return content

        # 최적의 자르기 지점 찾기
        return self._find_best_truncation(content, max_length)

    def _find_best_truncation(self, content: str, max_length: int) -> str:
        """최적의 자르기 지점 찾기"""

        # 전략 1: 완전한 문장 끝 찾기
        perfect_endings = ['다.', '요.', '습니다.', '합니다.', '됩니다.', '입니다.',
                          '었습니다.', '았습니다.', '였습니다.', '있습니다.', '것입니다.']

        search_start = max(max_length // 2, max_length - 150)

        for end_pos in range(min(len(content), max_length + 50), search_start, -1):
            if end_pos <= len(content):
                for ending in perfect_endings:
                    if content[end_pos - len(ending):end_pos] == ending:
                        # 실제 문장 끝인지 확인
                        if end_pos == len(content) or content[end_pos:end_pos+1].isspace():
                            return content[:end_pos].strip()

        # 전략 2: 구두점 + 공백 찾기
        truncated = content[:max_length]
        for i in range(len(truncated) - 1, max(0, len(truncated) - 100), -1):
            if i < len(truncated) - 1:
                char = truncated[i]
                next_char = truncated[i + 1]

                if char in '.!?' and (next_char.isspace() or next_char.isupper()):
                    return content[:i + 1].strip()

        # 전략 3: 한국어 동사/형용사 어미 찾기
        korean_endings = ['다', '요', '니다', '습니다', '합니다', '됩니다',
                         '입니다', '었다', '았다', '였다']

        for ending in korean_endings:
            for i in range(min(len(content), max_length), max(0, max_length - 100), -1):
                if content[i - len(ending):i] == ending:
                    # 공백, 마침표 또는 텍스트 끝인지 확인
                    if i == len(content) or content[i:i+1] in ' .,!?':
                        return content[:i].strip()

        # 전략 4: 단어 경계에서 자르기
        truncated = content[:max_length]
        last_space = truncated.rfind(' ')
        if last_space > max_length * 0.7:
            return content[:last_space].strip() + "..."

        # 전략 5: 마지막 수단 - 단어를 깨지 않게 자르기
        words = truncated.split()
        if len(words) > 1:
            return ' '.join(words[:-1]).strip() + "..."
        else:
            return truncated.rstrip() + "..."

    def format_citation(self, url: str) -> str:
        """인용 정보 포맷팅"""
        if not url or url.strip() == "":
            return ""

        url = url.strip()

        try:
            parsed = urlparse(url)
            domain = parsed.netloc

            # www. 접두사 제거
            if domain.startswith('www.'):
                domain = domain[4:]

            return f"\n   *출처: {domain}* ([링크]({url}))"

        except Exception:
            return f"\n   *출처: [링크]({url})*"

    def calculate_similarity(self, text1: str, text2: str) -> float:
        """두 텍스트 간 유사도 계산 (Jaccard 유사도)"""
        if not text1 or not text2:
            return 0.0

        words1 = set(text1.split())
        words2 = set(text2.split())

        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))

        if union == 0:
            return 0.0

        return intersection / union

    def extract_keywords(self, text: str, max_keywords: int = 10) -> List[str]:
        """텍스트에서 키워드 추출"""
        if not text:
            return []

        # 간단한 키워드 추출 (실제로는 더 정교한 NLP 기법 사용)
        words = text.lower().split()

        # 불용어 제거 (간단한 버전)
        stop_words = {'의', '가', '이', '은', '는', '을', '를', '에', '와', '과', '으로', '로'}
        keywords = [word for word in words if word not in stop_words and len(word) > 1]

        # 빈도 계산
        word_freq = {}
        for word in keywords:
            word_freq[word] = word_freq.get(word, 0) + 1

        # 빈도순 정렬 후 상위 키워드 반환
        sorted_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [word for word, freq in sorted_keywords[:max_keywords]]

    def clean_content(self, content: str) -> str:
        """콘텐츠 정리"""
        if not content:
            return ""

        # 기본 정리
        content = content.strip()
        content = ' '.join(content.split())

        # 아티팩트 제거
        for artifact in self.artifacts_to_remove:
            content = content.replace(artifact, '')

        return content.strip()