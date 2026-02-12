"""Internationalization support for OLAV.

Phase 10: Multi-language support for user interface and messages.

Features:
- Message translation system
- Locale-aware formatting
- Language preference management
- Dynamic language switching
"""

import logging
from typing import Dict, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class Language(Enum):
    """Supported languages."""
    CHINESE_SIMPLIFIED = "zh_CN"
    CHINESE_TRADITIONAL = "zh_TW"
    ENGLISH = "en_US"
    SPANISH = "es_ES"
    FRENCH = "fr_FR"
    GERMAN = "de_DE"
    JAPANESE = "ja_JP"


class LocalizationManager:
    """Manages message translation and localization.
    
    Provides:
    - Message translation
    - Language switching
    - Locale-aware formatting
    - Default fallback
    """
    
    # Message translation dictionary
    TRANSLATIONS = {
        "zh_CN": {
            # Common messages
            "plan_generated": "📋 执行计划已生成",
            "plan_approved": "✅ 用户已确认计划",
            "plan_rejected": "❌ 用户拒绝执行",
            "execution_started": "▶️  执行已开始",
            "execution_completed": "✅ 执行完成",
            "execution_failed": "❌ 执行失败",
            
            # Validation messages
            "validation_passed": "✅ 验证通过",
            "validation_failed": "❌ 验证失败",
            "input_empty": "查询不能为空",
            "input_too_long": "查询过长",
            
            # Status messages
            "status_pending": "待处理",
            "status_executing": "执行中",
            "status_completed": "已完成",
            "status_failed": "已失败",
            
            # Error messages
            "error_timeout": "操作超时",
            "error_network": "网络连接失败",
            "error_resource": "资源不足",
            
            # Dashboard
            "dashboard_title": "执行仪表板",
            "dashboard_success_rate": "成功率",
            "dashboard_avg_duration": "平均耗时",
            "dashboard_health_status": "健康状态",
            
            # Performance
            "performance_cache_hits": "缓存命中",
            "performance_cache_misses": "缓存未命中",
            "performance_optimization": "性能优化"
        },
        "en_US": {
            # Common messages
            "plan_generated": "📋 Execution plan generated",
            "plan_approved": "✅ Plan approved by user",
            "plan_rejected": "❌ Plan rejected by user",
            "execution_started": "▶️  Execution started",
            "execution_completed": "✅ Execution completed",
            "execution_failed": "❌ Execution failed",
            
            # Validation messages
            "validation_passed": "✅ Validation passed",
            "validation_failed": "❌ Validation failed",
            "input_empty": "Query cannot be empty",
            "input_too_long": "Query too long",
            
            # Status messages
            "status_pending": "Pending",
            "status_executing": "Executing",
            "status_completed": "Completed",
            "status_failed": "Failed",
            
            # Error messages
            "error_timeout": "Operation timeout",
            "error_network": "Network connection failed",
            "error_resource": "Resource exhausted",
            
            # Dashboard
            "dashboard_title": "Execution Dashboard",
            "dashboard_success_rate": "Success Rate",
            "dashboard_avg_duration": "Average Duration",
            "dashboard_health_status": "Health Status",
            
            # Performance
            "performance_cache_hits": "Cache Hits",
            "performance_cache_misses": "Cache Misses",
            "performance_optimization": "Performance Optimization"
        }
    }
    
    def __init__(self, language: Language = Language.CHINESE_SIMPLIFIED):
        """Initialize localization manager.
        
        Args:
            language: Default language
        """
        self.current_language = language.value
        self.language_map = {lang.value: lang for lang in Language}
    
    def set_language(self, language: Language) -> None:
        """Set current language.
        
        Args:
            language: Language to use
        """
        self.current_language = language.value
        logger.info(f"Language switched to: {language.value}")
    
    def get_message(self, key: str, **kwargs) -> str:
        """Get translated message.
        
        Args:
            key: Message key
            **kwargs: Format parameters
        
        Returns:
            Translated and formatted message
        """
        # Get translation for current language
        translations = self.TRANSLATIONS.get(self.current_language, {})
        message = translations.get(key)
        
        # Fallback to English if not found
        if not message:
            translations = self.TRANSLATIONS.get("en_US", {})
            message = translations.get(key, key)
        
        # Format with parameters if provided
        if kwargs:
            try:
                message = message.format(**kwargs)
            except (KeyError, ValueError) as e:
                logger.warning(f"Error formatting message '{key}': {e}")
        
        return message
    
    def get_language_name(self, language: Language) -> str:
        """Get human-readable language name.
        
        Args:
            language: Language enum
        
        Returns:
            Language name in current language
        """
        names = {
            Language.CHINESE_SIMPLIFIED: "简体中文" if self.current_language == "zh_CN" else "Chinese (Simplified)",
            Language.CHINESE_TRADITIONAL: "繁體中文" if self.current_language == "zh_CN" else "Chinese (Traditional)",
            Language.ENGLISH: "English",
            Language.SPANISH: "Español",
            Language.FRENCH: "Français",
            Language.GERMAN: "Deutsche",
            Language.JAPANESE: "日本語"
        }
        return names.get(language, language.value)
    
    def get_available_languages(self) -> Dict[str, str]:
        """Get list of available languages.
        
        Returns:
            Dict of language codes and names
        """
        return {
            lang.value: self.get_language_name(lang)
            for lang in Language
        }
    
    def format_duration(self, seconds: float) -> str:
        """Format duration in localized format.
        
        Args:
            seconds: Duration in seconds
        
        Returns:
            Formatted duration string
        """
        if self.current_language == "zh_CN":
            if seconds < 60:
                return f"{seconds:.1f}秒"
            elif seconds < 3600:
                minutes = seconds / 60
                return f"{minutes:.1f}分钟"
            else:
                hours = seconds / 3600
                return f"{hours:.1f}小时"
        else:
            if seconds < 60:
                return f"{seconds:.1f}s"
            elif seconds < 3600:
                minutes = seconds / 60
                return f"{minutes:.1f}min"
            else:
                hours = seconds / 3600
                return f"{hours:.1f}h"
    
    def format_percentage(self, value: float) -> str:
        """Format percentage in localized format.
        
        Args:
            value: Percentage value (0-100)
        
        Returns:
            Formatted percentage string
        """
        if self.current_language == "zh_CN":
            return f"{value:.1f}%"
        else:
            return f"{value:.1f}%"
    
    def format_number(self, value: float, decimal_places: int = 2) -> str:
        """Format number in localized format.
        
        Args:
            value: Numeric value
            decimal_places: Number of decimal places
        
        Returns:
            Formatted number string
        """
        if self.current_language == "zh_CN":
            # Chinese uses dot for decimal
            return f"{value:.{decimal_places}f}"
        else:
            return f"{value:.{decimal_places}f}"


class I18nHelper:
    """Helper functions for internationalization.
    
    Provides utilities for working with multiple languages.
    """
    
    @staticmethod
    def get_system_language() -> Language:
        """Detect system language preference.
        
        Returns:
            Detected Language enum
        """
        import locale
        
        system_locale = locale.getdefaultlocale()[0]
        
        # Map system locale to our Language enum
        locale_map = {
            "zh_CN": Language.CHINESE_SIMPLIFIED,
            "zh_TW": Language.CHINESE_TRADITIONAL,
            "en_US": Language.ENGLISH,
            "es_ES": Language.SPANISH,
            "fr_FR": Language.FRENCH,
            "de_DE": Language.GERMAN,
            "ja_JP": Language.JAPANESE
        }
        
        return locale_map.get(system_locale, Language.ENGLISH)
    
    @staticmethod
    def add_translation(
        language: Language,
        key: str,
        value: str
    ) -> None:
        """Add or update translation for a language.
        
        Args:
            language: Target language
            key: Message key
            value: Translated message
        """
        if language.value not in LocalizationManager.TRANSLATIONS:
            LocalizationManager.TRANSLATIONS[language.value] = {}
        
        LocalizationManager.TRANSLATIONS[language.value][key] = value
        logger.debug(f"Added translation for {language.value}: {key}")


# Global singleton instance
_i18n_instance: Optional[LocalizationManager] = None


def get_localization_manager(
    language: Optional[Language] = None
) -> LocalizationManager:
    """Get or create singleton localization manager.
    
    Args:
        language: Optional language to set on creation
    
    Returns:
        Shared LocalizationManager instance
    """
    global _i18n_instance
    
    if _i18n_instance is None:
        if language is None:
            language = I18nHelper.get_system_language()
        _i18n_instance = LocalizationManager(language)
    
    return _i18n_instance
