# P2.2 Display Module Optimization Plan

**Objective**: Optimize display.py module for better code quality and reusability

## Analysis

### Current Situation
- ✅ 3 functions added in P1.2 (print_error, print_success, print_welcome)
- ✅ __all__ list created with 7 exports
- ⚠️ Code duplication in print_* functions (repetitive Rich fallback logic)
- ⚠️ No return types specified
- ⚠️ No constant format strings

### Optimization Opportunities

1. **Reduce Code Duplication** (Priority HIGH)
   - Extract common pattern into `_format_and_print()` helper
   - DRY principle: eliminate repetitive console creation and fallback logic
   - Current: 73 lines → Target: ~40 lines

2. **Improve Type Annotations** (Priority MEDIUM)
   - Add return type hints to all functions
   - Add type hints to Optional console parameter

3. **Standardize Format Strings** (Priority MEDIUM)
   - Define emoji and format constants
   - Allow customization of emoji prefixes

4. **Add Documentation** (Priority LOW)
   - Module docstring improvements
   - Function docstring examples

## Implementation Plan

### Step 1: Create Helper Function
```python
def _format_and_print(
    message: str,
    format_key: str,
    console: Console | None = None,
    fallback_prefix: str = "",
) -> None:
    """Internal helper for print_* functions."""
```

### Step 2: Refactor Print Functions
- print_error() - uses format_key="error"
- print_success() - uses format_key="success"
- print_welcome() - uses format_key="welcome"

### Step 3: Create Format Configuration
```python
_FORMAT_CONFIG = {
    "error": {"emoji": "❌", "style": "bold red", "prefix": "ERROR:"},
    "success": {"emoji": "✅", "style": "bold green", "prefix": "SUCCESS:"},
    "welcome": {"emoji": "👋", "style": "bold cyan", "prefix": ""},
}
```

### Step 4: Verify & Test
- ✅ All exports still work
- ✅ Similar behavior to original
- ✅ Code reduction of ~35-40%
- ✅ Type hints complete
- ✅ No breaking changes

## Expected Results

**Before**: 73 lines (print_* functions) + repetitive code
**After**: 40-45 lines + helper function + cleaner code

**Benefits**:
- ✅ DRY principle applied
- ✅ Easier to add new print_* variants
- ✅ Type-safe
- ✅ Better documentation
- ✅ Same functionality

## Success Criteria

- [ ] Code reduction of 25-35%
- [ ] All tests still pass
- [ ] No breaking changes
- [ ] Complete type hints
- [ ] Cleaner, more maintainable code
