# Deprecated E2E Tests (v0.10.1+)

This directory contains deprecated E2E test files that have been superseded by the new testing standard.

## Migration Status

### New Standard: `tests/e2e/test_real_scenarios.py`
- ✅ **Active Standard** since v0.10.1
- 21 comprehensive E2E tests
- Zero-mock policy with real LLM calls
- All tests PASS

### Deprecated Files

#### `test_zero_mock_real.py` (Archived)
- Old zero-mock E2E test file
- 18 tests - mostly duplicates of test_real_scenarios.py
- Archived: v0.10.1 (2026-02-06)
- **Status**: All functionality merged into test_real_scenarios.py

#### `test_production_real.py` (Archived)
- Old production E2E test file
- 5 tests - legacy format
- Archived: v0.10.1 (2026-02-06)
- **Status**: Functionality simplified and integrated into test_real_scenarios.py

## Why Archived

Per v0.10.1 Real E2E Testing Standards:

1. **Test Consolidation**: Multiple test files were testing same scenarios
2. **Code Quality**: test_real_scenarios.py has:
   - Better structure and organization
   - Clearer test descriptions
   - More comprehensive scenarios
   - Better side-effect tracking

3. **Elimination of Redundancy**: Removed duplicate test coverage

## Restoration Instructions

If you need to restore old test files:

```bash
# Restore old test files to tests/e2e/
git mv archive/deprecated_e2e_tests/test_zero_mock_real.py tests/e2e/
git mv archive/deprecated_e2e_tests/test_production_real.py tests/e2e/
```

## Reference

For current E2E testing standards, see:
- `/home/yhvh/Olav/docs/08_TESTING_GIT_CICD_GUIDE.md`
- `/home/yhvh/Olav/copilot-instructions.md` (§ Real E2E Testing Standards)
