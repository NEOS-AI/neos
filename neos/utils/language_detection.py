import re


def detect_language(query: str) -> str:
    # 각 언어별 문자 수 카운트
    korean_chars = len(re.findall(r'[가-힣]', query))

    # 일본어: 히라가나, 가타카나, 한자 포함
    hiragana_chars = len(re.findall(r'[ぁ-ん]', query))
    katakana_chars = len(re.findall(r'[ァ-ヶー]', query))
    kanji_chars = len(re.findall(r'[一-龯]', query))

    # 일본어는 히라가나/가타카나가 있으면 확실
    japanese_chars = hiragana_chars + katakana_chars + kanji_chars
    has_kana = hiragana_chars > 0 or katakana_chars > 0

    # 중국어: 한자만 (일본어 가나가 없을 때)
    chinese_chars = kanji_chars if not has_kana else 0

    english_chars = len(re.findall(r'[a-zA-Z]', query))

    # 총 문자 수 (공백 제외)
    total_chars = len(re.findall(r'\S', query))

    if total_chars == 0:
        return 'en'  # 기본값

    # 일본어 확정: 히라가나나 가타카나가 있으면
    if has_kana and japanese_chars / total_chars >= 0.3:
        return 'ja'

    # 각 언어 비율 계산
    lang_ratios = {
        'ko': korean_chars / total_chars,
        'ja': japanese_chars / total_chars,
        'zh': chinese_chars / total_chars,
        'en': english_chars / total_chars
    }

    # 가장 높은 비율의 언어 선택 (최소 30% 이상)
    max_lang = max(lang_ratios, key=lang_ratios.get)
    max_ratio = lang_ratios[max_lang]

    # 30% 미만이면 영어로 기본 설정
    if max_ratio < 0.3:
        return 'en'

    return max_lang
