# HyperDeepResearch Iterative Refinement Tests

## Overview

This directory contains comprehensive unit and integration tests for the Ralph Loop-inspired iterative refinement system in HyperDeepResearch.

## Test Coverage

### Unit Tests (`test_iterative_refiner.py`)

**Total: 25+ test cases**

#### 1. SectionQuality Tests (7 tests)
- ✅ `test_overall_score_calculation`: Weighted score calculation
- ✅ `test_to_dict_conversion`: Dictionary serialization
- ✅ `test_improvement_suggestions_low_citations`: Citation-related suggestions
- ✅ `test_improvement_suggestions_low_coherence`: Coherence-related suggestions
- ✅ `test_improvement_suggestions_multiple_issues`: Multiple improvement detection

#### 2. SectionIterator Tests (5 tests)
- ✅ `test_refine_section_meets_threshold_first_iteration`: Quick convergence
- ✅ `test_refine_section_max_iterations_reached`: Max iteration handling
- ✅ `test_refine_section_empty_content`: Edge case - empty content
- ✅ `test_refine_section_very_long_content`: Edge case - >10,000 words
- ✅ `test_refine_section_without_citations`: Edge case - no citations

#### 3. AbstractGenerator Tests (3 tests)
- ✅ `test_generate_abstract_from_summaries`: Abstract generation
- ✅ `test_refine_abstract_not_needed`: Skip unnecessary refinement
- ✅ `test_refine_abstract_needed`: Perform needed refinement

#### 4. ConsistencyAligner Tests (3 tests)
- ✅ `test_align_section_already_consistent`: No-op when consistent
- ✅ `test_align_section_with_issues`: Fix consistency issues
- ✅ `test_align_section_with_invalid_citations_auto_fix`: Auto-fix citations

#### 5. Retry Decorator Tests (5 tests)
- ✅ `test_retry_success_on_first_attempt`: No retry needed
- ✅ `test_retry_success_after_transient_error`: Successful retry
- ✅ `test_retry_failure_after_max_attempts`: Max retry exhaustion
- ✅ `test_retry_non_transient_error_no_retry`: Non-transient error handling
- ✅ `test_retry_timeout_error`: TimeoutError retry

#### 6. Basic Orchestration Tests (2 tests)
- ✅ `test_initialization`: Proper initialization
- ✅ `test_config_loading`: Config loading and defaults

### Integration Tests (`../../integration/test_iterative_refinement_integration.py`)

**Total: 7+ integration scenarios**

#### 1. Full Process Tests (2 scenarios)
- ✅ `test_end_to_end_refinement`: Complete 4-phase process
- ✅ `test_parallel_refinement_performance`: Parallel vs sequential timing

#### 2. Config-Driven Behavior (2 scenarios)
- ✅ `test_quality_threshold_config`: Config threshold respected
- ✅ `test_disabled_refinement_config`: Disable refinement behavior

#### 3. Error Handling (2 scenarios)
- ✅ `test_llm_failure_retry`: LLM failure recovery
- ✅ `test_citation_auto_fix_integration`: Citation auto-fix end-to-end

#### 4. Performance Metrics (1 scenario)
- ✅ `test_refinement_metadata_tracking`: Metadata tracking

## Running Tests

### Prerequisites

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Ensure NEOS is installed in development mode
pip install -e .
```

### Run Unit Tests

```bash
# Run all unit tests
pytest tests/unit/agents/hyper_deep_research/ -v

# Run with coverage
pytest tests/unit/agents/hyper_deep_research/ --cov=neos.agents.search_agents.hyper_deep_research.iterative_refiner --cov-report=html

# Run specific test class
pytest tests/unit/agents/hyper_deep_research/test_iterative_refiner.py::TestSectionQuality -v

# Run specific test
pytest tests/unit/agents/hyper_deep_research/test_iterative_refiner.py::TestSectionQuality::test_overall_score_calculation -v
```

### Run Integration Tests

```bash
# Run all integration tests
pytest tests/integration/test_iterative_refinement_integration.py -v -m integration

# Run without integration marker (unit tests only)
pytest tests/unit/agents/hyper_deep_research/ -v -m "not integration"
```

### Coverage Report

```bash
# Generate HTML coverage report
pytest tests/unit/agents/hyper_deep_research/ \
  --cov=neos.agents.search_agents.hyper_deep_research.iterative_refiner \
  --cov-report=html \
  --cov-report=term-missing

# View coverage report
open htmlcov/index.html
```

**Expected Coverage**: 80%+ for `iterative_refiner.py`

## Test Strategy

### 1. Mock External Dependencies
All LLM calls are mocked to ensure:
- Fast test execution
- No API costs
- Deterministic results
- No network dependencies

### 2. Test Edge Cases
Edge cases covered:
- Empty content
- Very long content (>10,000 words)
- No citations
- Max iterations reached
- Transient errors
- Invalid citations

### 3. Verify Error Handling
Error scenarios tested:
- LLM timeouts
- Rate limiting (429)
- Server errors (503)
- Non-transient errors
- Citation validation failures

### 4. Performance Validation
Performance aspects tested:
- Parallel vs sequential execution
- Metadata tracking
- Duration measurement

## Known Issues

### Circular Import

**Issue**: `ImportError: cannot import name 'DataAnalysisAgent' from partially initialized module`

**Root Cause**: Circular dependency in `neos.agents` and `neos.workflow` modules (existing project issue)

**Workaround**:
```python
# Option 1: Run tests with PYTHONPATH
PYTHONPATH=/Users/ywsung/Desktop/neos pytest tests/unit/...

# Option 2: Direct module loading (implemented in test file)
# Uses importlib.util.spec_from_file_location to bypass circular import
```

**Status**: Pending project-wide refactor to resolve circular imports

## Test Markers

Tests use pytest markers for organization:

- `@pytest.mark.asyncio`: Async tests
- `@pytest.mark.integration`: Integration tests
- `@pytest.mark.slow`: Slow-running tests (>1s)

Run specific markers:
```bash
# Only async tests
pytest -m asyncio

# Skip integration tests
pytest -m "not integration"

# Only slow tests
pytest -m slow
```

## Adding New Tests

### 1. Test Structure

```python
class TestNewFeature:
    """Test description."""

    @pytest.mark.asyncio
    async def test_feature_behavior(self, fixture_name):
        """Test specific behavior."""
        # Arrange
        setup_code()

        # Act
        result = await function_under_test()

        # Assert
        assert result == expected_value
```

### 2. Fixtures

Add fixtures to `conftest.py` or in test file:

```python
@pytest.fixture
def my_fixture():
    """Fixture description."""
    return setup_data()
```

### 3. Mocking LLM Calls

```python
with patch("path.to.create_tracked_llm") as mock_llm_factory:
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = MagicMock(content="response")
    mock_llm_factory.return_value = mock_llm

    # Run test
    result = await function_that_calls_llm()
```

## Continuous Integration

### GitHub Actions (Recommended)

```yaml
name: Test Iterative Refinement

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.12'
      - run: pip install -e .[dev]
      - run: pytest tests/unit/agents/hyper_deep_research/ --cov --cov-report=xml
      - uses: codecov/codecov-action@v2
```

### Pre-commit Hook

```bash
# .git/hooks/pre-commit
#!/bin/bash
pytest tests/unit/agents/hyper_deep_research/ --exitfirst
```

## Test Data

Test data locations:
- Mock data: Inline in test files
- Fixtures: `conftest.py`
- Sample sections: `sample_sections_data` fixture

## References

1. **pytest Documentation**: https://docs.pytest.org/
2. **pytest-asyncio**: https://pytest-asyncio.readthedocs.io/
3. **unittest.mock**: https://docs.python.org/3/library/unittest.mock.html
4. **Enhancement Roadmap**: `docs/HYPER_DEEP_RESEARCH_RALPH_LOOP_ENHANCEMENTS.md`

---

**Last Updated**: 2026-01-10
**Test Coverage Target**: 80%+
**Maintainer**: NEOS Development Team
