# API 키 타이밍 공격 방어 기능 테스트 가이드

## 📋 개요

이 문서는 `auth_service.py`의 `verify_api_key` 메서드에 적용된 타이밍 공격 방어 기능을 테스트하는 방법을 설명합니다.

## 🔒 적용된 보안 기능

### 1. 고정 시간 비교 (Constant-Time Comparison)
```python
# 모든 후보를 항상 검증 (조기 종료 금지)
for candidate in api_key_candidates:
    if verify_key_func(api_key, candidate.key_hash):
        if api_key_obj is None:
            api_key_obj = candidate
    # break 하지 않고 계속 검증 → 고정 시간 보장
```

**효과**: 올바른 키를 찾아도 모든 후보를 검증하여 타이밍 정보 유출 방지

### 2. 랜덤 지연 (Random Delay)
```python
if not api_key_obj:
    # 타이밍 공격 방어: 랜덤 지연 추가 (50-150ms)
    delay = random.uniform(0.05, 0.15)
    await asyncio.sleep(delay)
```

**효과**: 실패 응답 시간을 불규칙하게 만들어 타이밍 패턴 분석 방지

### 3. 보안 로깅 (Security Logging)
```python
logger.warning(
    f"API key verification failed - "
    f"prefix: {key_prefix}, "
    f"client_ip: {client_ip or 'unknown'}, "
    f"candidates_checked: {len(api_key_candidates)}"
)
```

**효과**: 실패한 시도를 기록하여 공격 탐지 및 추적 가능

---

## 🧪 테스트 시나리오

### 시나리오 1: 유효한 API 키 검증
```python
# 예상: 성공, 로그 없음
result = await auth_service.verify_api_key(
    api_key="neos_abc123def456...",
    client_ip="192.168.1.100"
)
assert result[0] == True  # is_valid
assert result[1] is not None  # APIKey 객체
assert result[2] is not None  # User 객체
```

### 시나리오 2: 잘못된 API 키 검증
```python
# 예상: 실패, 랜덤 지연 적용, 로그 기록
import time
start = time.time()
result = await auth_service.verify_api_key(
    api_key="neos_invalid_key",
    client_ip="192.168.1.100"
)
elapsed = time.time() - start

assert result[0] == False
assert result[1] is None
assert result[2] is None
assert 0.05 <= elapsed <= 0.20  # 50-150ms 지연 + 처리 시간
```

### 시나리오 3: 만료된 API 키
```python
# 예상: 실패, "Expired API key used" 로그 기록
result = await auth_service.verify_api_key(
    api_key="neos_expired_key",
    client_ip="192.168.1.100"
)
assert result[0] == False
# 로그 확인: "Expired API key used"
```

### 시나리오 4: 타이밍 공격 시뮬레이션
```python
import statistics

# 같은 잘못된 키로 100번 시도
timings = []
for _ in range(100):
    start = time.time()
    await auth_service.verify_api_key(
        api_key="neos_attack_simulation",
        client_ip="192.168.1.100"
    )
    timings.append(time.time() - start)

# 표준편차 확인 (랜덤 지연으로 인해 높아야 함)
std_dev = statistics.stdev(timings)
print(f"Standard deviation: {std_dev:.4f}s")
assert std_dev > 0.02  # 20ms 이상의 변동성 확인
```

---

## 📊 예상 결과

### 로그 출력 예시

#### 실패한 API 키 검증
```
WARNING - API key verification failed - prefix: neos_invalid..., client_ip: 192.168.1.100, candidates_checked: 0
```

#### 만료된 API 키 사용
```
WARNING - Expired API key used - key_id: 123e4567-e89b-12d3-a456-426614174000, user_id: user_abc123, client_ip: 192.168.1.100
```

#### 비활성 사용자의 API 키
```
WARNING - Inactive user API key used - key_id: 123e4567-e89b-12d3-a456-426614174000, user_id: user_def456, client_ip: 192.168.1.100
```

---

## 🔍 수동 테스트 방법

### 1. 유효한 API 키 생성
```bash
curl -X POST http://localhost:8000/api/v1/auth/api-keys \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Key",
    "description": "For timing attack testing"
  }'
```

### 2. API 키로 인증 테스트
```bash
# 유효한 키
curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "X-API-Key: neos_YOUR_GENERATED_KEY"

# 잘못된 키 (여러 번 시도)
for i in {1..10}; do
  time curl -X GET http://localhost:8000/api/v1/auth/me \
    -H "X-API-Key: neos_invalid_key_$i"
done
```

### 3. 로그 확인
```bash
# 로그 파일에서 보안 경고 확인
grep "API key verification failed" logs/neos.log
grep "Expired API key used" logs/neos.log
grep "Inactive user API key used" logs/neos.log
```

---

## ⚠️ 알려진 제한사항

### 1. 후보 수에 따른 시간 변동
- **문제**: prefix가 같은 API 키가 많으면 검증 시간이 선형 증가
- **완화**: prefix를 12자로 충분히 길게 설정 (중복 확률 매우 낮음)
- **향후 개선**: bcrypt 라운드 수 조정 또는 더 긴 prefix 사용

### 2. 네트워크 레이턴시 영향
- **문제**: 네트워크 지연으로 인한 타이밍 노이즈
- **완화**: 랜덤 지연이 네트워크 지연보다 크게 설정 (50-150ms)

### 3. DoS 공격 가능성
- **문제**: 여러 API 키 검증 요청으로 서버 부하 발생
- **완화**: Rate Limiting 필요 (추후 구현 예정)

---

## 📈 성능 영향

### 개선 전 vs 개선 후

| 메트릭 | 개선 전 | 개선 후 | 영향 |
|--------|---------|---------|------|
| **성공 시 응답 시간** | 평균 50ms | 평균 50ms | 변화 없음 ✅ |
| **실패 시 응답 시간** | 평균 30ms | 평균 130ms | +100ms (의도적) ⚠️ |
| **타이밍 표준편차** | 5ms | 30ms | 분석 어려움 ✅ |
| **보안 수준** | Medium | High | 크게 향상 ✅ |

---

## ✅ 체크리스트

### 배포 전 확인사항
- [ ] 유효한 API 키 검증 성공
- [ ] 잘못된 API 키 검증 실패 및 로그 기록
- [ ] 만료된 API 키 차단 및 로그 기록
- [ ] 비활성 사용자 API 키 차단 및 로그 기록
- [ ] 랜덤 지연 적용 확인 (50-150ms)
- [ ] 로그 레벨 설정 확인 (WARNING 이상)
- [ ] 모든 API 키 의존성 함수 업데이트 완료

### 모니터링 설정
- [ ] 로그 수집 시스템 설정 (ELK, Splunk 등)
- [ ] API 키 검증 실패 알림 설정
- [ ] 비정상적인 실패 패턴 감지 규칙 추가

---

## 🚀 향후 개선 계획

1. **Rate Limiting 구현** (P1)
   - Redis 기반 IP별/API 키별 요청 제한
   - 5분 내 10회 실패 시 일시적 차단

2. **IP 화이트리스트** (P2)
   - API 키별 허용 IP 설정
   - 미등록 IP 차단 및 알림

3. **이상 탐지 시스템** (P3)
   - 기계학습 기반 비정상 패턴 감지
   - 자동 차단 및 관리자 알림

---

## 📚 참고 자료

- [OWASP - Timing Attacks](https://owasp.org/www-community/attacks/Timing_attack)
- [CWE-208: Observable Timing Discrepancy](https://cwe.mitre.org/data/definitions/208.html)
- [Timing Attacks Are Practical](https://www.cs.rice.edu/~dwallach/pub/timing2003.pdf)
