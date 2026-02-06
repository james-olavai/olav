"""Input validation for plan mode execution.

Phase 6.2.4: Input validation ensures user queries are valid before plan generation.

Features:
- Query string validation (non-empty, length limits)
- Special character filtering (prevent injection)
- Intent classification (identify query type)
- Dependency validation (verify subagent dependencies)
- Error reporting with user-friendly messages
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of input validation.
    
    Attributes:
        is_valid: Whether validation passed
        cleaned_query: Sanitized query string
        intent_type: Classified intent type (sync, query, report, etc)
        errors: List of validation errors (if any)
        warnings: List of validation warnings
    """
    is_valid: bool
    cleaned_query: str
    intent_type: str
    errors: List[str]
    warnings: List[str]


class PlanInputValidator:
    """Validator for plan mode inputs.
    
    Handles:
    - Query string validation
    - Intent classification
    - Special character filtering
    - Length limit checks
    - Dependency validation
    """
    
    # Configuration constants
    MIN_QUERY_LENGTH = 2
    MAX_QUERY_LENGTH = 500
    MAX_INTENT_LENGTH = 200
    
    # Intent patterns
    SYNC_INTENT_PATTERNS = [
        r"同步.*(?:到|至|进|导入)", r"导入.*设备", r"上传.*设备",
        r"更新.*数据库", r"导出.*到.*netbox"
    ]
    QUERY_INTENT_PATTERNS = [
        r"查询.*设备", r"查看.*信息", r"获取.*数据",
        r"列表.*设备", r"显示.*(?:所有|列表)"
    ]
    REPORT_INTENT_PATTERNS = [
        r"生成.*报告", r"导出.*(?:报告|文件)", r"对比.*数据",
        r"统计.*信息"
    ]
    ANALYZE_INTENT_PATTERNS = [
        r"分析.*数据", r"对比.*设备", r"检查.*差异",
        r"验证.*(?:数据|配置)"
    ]
    
    # Dangerous patterns (SQL injection, code injection, etc)
    DANGEROUS_PATTERNS = [
        r"[;'\"`]|--|\*\*|\|\|",  # SQL injection
        r"\$\{.*\}|\$\(.*\)",       # Template injection
        r"<script|javascript:|onerror",  # XSS
        r"exec\(|eval\(|import\s",      # Code injection
        r"\.\./|\\\\",                    # Path traversal
    ]
    
    # Safe characters pattern
    SAFE_CHAR_PATTERN = r"^[\w\u4e00-\u9fff\s\-()（）【】、。，]+$"
    
    def __init__(self):
        """Initialize validator with default settings."""
        self.sync_pattern = self._compile_patterns(self.SYNC_INTENT_PATTERNS)
        self.query_pattern = self._compile_patterns(self.QUERY_INTENT_PATTERNS)
        self.report_pattern = self._compile_patterns(self.REPORT_INTENT_PATTERNS)
        self.analyze_pattern = self._compile_patterns(self.ANALYZE_INTENT_PATTERNS)
        self.dangerous_pattern = self._compile_patterns(self.DANGEROUS_PATTERNS)
    
    @staticmethod
    def _compile_patterns(patterns: List[str]) -> re.Pattern:
        """Compile multiple patterns into single regex."""
        combined = "|".join(patterns)
        return re.compile(combined, re.IGNORECASE | re.UNICODE)
    
    def validate(self, user_intent: str) -> ValidationResult:
        """Validate user intent for plan mode.
        
        Args:
            user_intent: Raw user query string
        
        Returns:
            ValidationResult with validation status and cleaned query
        """
        errors = []
        warnings = []
        intent_type = "unknown"
        
        # 1. Check if query is empty or only whitespace
        if not user_intent or not user_intent.strip():
            errors.append("查询不能为空")
            return ValidationResult(
                is_valid=False,
                cleaned_query="",
                intent_type=intent_type,
                errors=errors,
                warnings=warnings
            )
        
        # 2. Strip whitespace
        cleaned = user_intent.strip()
        
        # 3. Check length limits
        if len(cleaned) < self.MIN_QUERY_LENGTH:
            errors.append(f"查询太短 (最少 {self.MIN_QUERY_LENGTH} 个字符)")
        
        if len(cleaned) > self.MAX_QUERY_LENGTH:
            errors.append(f"查询太长 (最多 {self.MAX_QUERY_LENGTH} 个字符)")
            cleaned = cleaned[:self.MAX_QUERY_LENGTH]
            warnings.append("查询已截断至最大长度")
        
        # 4. Check for dangerous patterns (security)
        if self.dangerous_pattern.search(cleaned):
            errors.append("查询包含不允许的字符或模式")
        
        # 5. Check for safe characters (allow Chinese, English, common punctuation)
        if not re.match(self.SAFE_CHAR_PATTERN, cleaned):
            # Try to extract safe portions
            safe_cleaned = self._extract_safe_chars(cleaned)
            if safe_cleaned:
                warnings.append(f"已从查询中移除不安全字符")
                cleaned = safe_cleaned
            else:
                errors.append("查询包含不支持的字符")
        
        # 6. Classify intent type
        intent_type = self._classify_intent(cleaned)
        
        # Return validation result
        is_valid = len(errors) == 0
        return ValidationResult(
            is_valid=is_valid,
            cleaned_query=cleaned,
            intent_type=intent_type,
            errors=errors,
            warnings=warnings
        )
    
    def _extract_safe_chars(self, text: str) -> str:
        """Extract only safe characters from text.
        
        Keeps:
        - Chinese characters (CJK)
        - English letters and numbers
        - Common punctuation that's safe: - ( ) （ ） 【 】 、 。 ， ' "
        """
        pattern = r"[\w\u4e00-\u9fff\s\-()（）【】、。，\'\"]"
        safe_chars = re.findall(pattern, text)
        return "".join(safe_chars).strip()
    
    def _classify_intent(self, query: str) -> str:
        """Classify the type of query (sync, query, report, analyze).
        
        Args:
            query: Cleaned query string
        
        Returns:
            Intent type: "sync", "query", "report", "analyze", or "unknown"
        """
        if self.sync_pattern.search(query):
            return "sync"
        elif self.query_pattern.search(query):
            return "query"
        elif self.report_pattern.search(query):
            return "report"
        elif self.analyze_pattern.search(query):
            return "analyze"
        else:
            return "unknown"
    
    def validate_dependencies(
        self, dependencies: List[Dict]
    ) -> Tuple[bool, List[str]]:
        """Validate dependency structure.
        
        Args:
            dependencies: List of dependency dicts with subagent, requires, etc
        
        Returns:
            Tuple of (is_valid, errors)
        """
        errors = []
        seen_outputs = set()
        
        for i, dep in enumerate(dependencies):
            # Check required fields
            if "subagent" not in dep:
                errors.append(f"依赖 {i}: 缺少 'subagent' 字段")
            
            if "output_context_key" not in dep:
                errors.append(f"依赖 {i}: 缺少 'output_context_key' 字段")
            else:
                output_key = dep["output_context_key"]
                if output_key in seen_outputs:
                    errors.append(f"依赖 {i}: 输出键重复: {output_key}")
                seen_outputs.add(output_key)
            
            # Check requires are valid (should be in previous outputs or empty)
            requires = dep.get("requires", [])
            for req in requires:
                if req not in seen_outputs:
                    errors.append(
                        f"依赖 {i}: 要求的输出 '{req}' 未在之前的步骤中生成"
                    )
        
        return len(errors) == 0, errors
    
    def get_user_friendly_message(self, result: ValidationResult) -> str:
        """Generate user-friendly validation message.
        
        Args:
            result: ValidationResult from validation
        
        Returns:
            Formatted message for user
        """
        if result.is_valid:
            msg = f"✅ 验证通过\n"
            msg += f"- 意图: {result.intent_type}\n"
            if result.warnings:
                for warning in result.warnings:
                    msg += f"- ⚠️  {warning}\n"
            return msg
        else:
            msg = f"❌ 验证失败\n\n**错误:**\n"
            for error in result.errors:
                msg += f"- {error}\n"
            if result.warnings:
                msg += f"\n**警告:**\n"
                for warning in result.warnings:
                    msg += f"- {warning}\n"
            return msg


# Global singleton instance
_validator_instance: Optional[PlanInputValidator] = None


def get_plan_input_validator() -> PlanInputValidator:
    """Get or create singleton PlanInputValidator instance.
    
    Returns:
        Shared PlanInputValidator instance
    """
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = PlanInputValidator()
    return _validator_instance
