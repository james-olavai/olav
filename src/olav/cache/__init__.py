"""
OLAV 统一缓存模块

提供三种匹配模式：
- exact: Hash 精确匹配（默认，< 1ms）
- fuzzy: 编辑距离模糊匹配（< 100ms）
- semantic: Embedding 语义匹配（预留，未实现）

使用场景：
- Query/CLI SubAgent: exact (精确)
- 主路由: fuzzy (容错)
"""

import hashlib
import json
import logging
import sqlite3
from typing import Any, Literal

try:
    from langchain_community.cache import SQLiteCache
    from langchain_core.globals import set_llm_cache
except ImportError:
    # 如果 langchain_community 不可用，使用空实现
    SQLiteCache = None
    set_llm_cache = None

from config.paths import CACHE_DIR

logger = logging.getLogger(__name__)

CACHE_DB = CACHE_DIR / "olav_cache.db"


def init_cache() -> None:
    """初始化所有缓存（启动时调用一次）"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. LangChain LLM 缓存（自动缓存所有 LLM 调用）
    if SQLiteCache and set_llm_cache:
        set_llm_cache(SQLiteCache(database_path=str(CACHE_DB)))
        logger.info(f"✅ LangChain LLM cache initialized: {CACHE_DB}")
    else:
        logger.warning("⚠️  LangChain cache not available, skipping LLM cache initialization")

    # 2. 创建自定义表
    conn = sqlite3.connect(CACHE_DB)
    conn.executescript("""
        -- Guard 静态黑名单（危险关键词）
        CREATE TABLE IF NOT EXISTS guard_blacklist (
            keyword TEXT PRIMARY KEY,
            reason TEXT,
            severity TEXT DEFAULT 'high',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Guard 动态拒绝缓存（非网络相关查询）
        CREATE TABLE IF NOT EXISTS guard_rejected (
            query_hash TEXT PRIMARY KEY,
            query_text TEXT,
            reject_reason TEXT,
            hit_count INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_hit TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Intent 缓存（支持多种匹配模式）
        CREATE TABLE IF NOT EXISTS intent_cache (
            query_hash TEXT PRIMARY KEY,
            query_text TEXT,
            result JSON,
            hit_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 预填充静态黑名单
        INSERT OR IGNORE INTO guard_blacklist (keyword, reason, severity) VALUES
            ('drop table', 'SQL injection attempt', 'critical'),
            ('delete from', 'Destructive SQL operation', 'critical'),
            ('truncate', 'Destructive SQL operation', 'critical'),
            ('rm -rf', 'Dangerous shell command', 'critical'),
            ('shutdown', 'System shutdown attempt', 'high'),
            ('format', 'Disk format attempt', 'high');

        -- 索引优化
        CREATE INDEX IF NOT EXISTS idx_guard_keyword ON guard_blacklist(keyword);
        CREATE INDEX IF NOT EXISTS idx_rejected_hash ON guard_rejected(query_hash);
        CREATE INDEX IF NOT EXISTS idx_intent_hash ON intent_cache(query_hash);
    """)
    conn.commit()
    conn.close()
    logger.info("✅ Custom cache tables initialized")


class OlavCache:
    """统一缓存接口 - 极简设计"""

    def __init__(self) -> None:
        self.db_path = str(CACHE_DB)

    def _hash(self, text: str) -> str:
        """规范化 + Hash"""
        import re

        normalized = text.lower().strip()
        # 保留关键差异（如设备名 R1 vs R2）
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"[？?!！。.,，]", "", normalized)
        return hashlib.md5(normalized.encode()).hexdigest()  # noqa: S324

    def _calculate_similarity(self, query1: str, query2: str) -> float:
        """计算两个查询的相似度（Fuzzy 模式用）"""
        from difflib import SequenceMatcher

        return SequenceMatcher(None, query1.lower(), query2.lower()).ratio()

    # ==================== Guard 静态黑名单 ====================

    def check_blacklist(self, query: str) -> tuple[bool, str | None]:
        """检查静态黑名单"""
        conn = sqlite3.connect(self.db_path)
        query_lower = query.lower()

        # 检查所有关键词
        result = conn.execute("SELECT keyword, reason FROM guard_blacklist").fetchall()
        conn.close()

        for keyword, reason in result:
            if keyword in query_lower:
                logger.warning(f"🚫 Blacklist blocked: {query[:50]} (reason: {reason})")
                return (True, f"🚫 Security blocked: {reason}")

        return (False, None)

    # ==================== Guard 动态拒绝缓存 ====================

    def check_rejected(self, query: str) -> tuple[bool, str | None]:
        """检查是否在动态拒绝缓存中"""
        query_hash = self._hash(query)
        conn = sqlite3.connect(self.db_path)

        result = conn.execute(
            "SELECT reject_reason FROM guard_rejected WHERE query_hash = ?", [query_hash]
        ).fetchone()

        if result:
            # 更新命中统计
            conn.execute(
                """UPDATE guard_rejected
                   SET hit_count = hit_count + 1, last_hit = CURRENT_TIMESTAMP
                   WHERE query_hash = ?""",
                [query_hash],
            )
            conn.commit()
            conn.close()
            logger.info(f"✅ Guard rejected cache HIT: {query[:50]}")
            return (True, result[0])

        conn.close()
        return (False, None)

    def add_rejected(self, query: str, reason: str) -> None:
        """添加到动态拒绝缓存（学习）"""
        query_hash = self._hash(query)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT OR REPLACE INTO guard_rejected
               (query_hash, query_text, reject_reason)
               VALUES (?, ?, ?)""",
            [query_hash, query, reason],
        )
        conn.commit()
        conn.close()
        logger.info(f"📝 Learned rejection: {query[:50]}")

    # ==================== Intent 缓存（支持多种匹配模式）====================

    def get_intent(
        self,
        query: str,
        match_mode: Literal["exact", "fuzzy", "semantic"] = "exact",
        confidence_threshold: float = 0.95,
    ) -> dict | None:
        """
        获取缓存的 Intent（支持多种匹配模式）

        Args:
            query: 用户查询
            match_mode: 匹配模式
                - "exact": Hash 精确匹配（默认，最快）
                - "fuzzy": 编辑距离模糊匹配（适合容错）
                - "semantic": Embedding 语义匹配（适合同义转述，未实现）
            confidence_threshold: 匹配置信度阈值（0.0-1.0）

        Returns:
            缓存结果 + _confidence 字段
        """
        conn = sqlite3.connect(self.db_path)

        if match_mode == "exact":
            # Tier 1a: Hash 精确匹配（< 1ms）
            query_hash = self._hash(query)
            result = conn.execute(
                "SELECT result FROM intent_cache WHERE query_hash = ?", [query_hash]
            ).fetchone()

            if result:
                conn.execute(
                    "UPDATE intent_cache SET hit_count = hit_count + 1 WHERE query_hash = ?",
                    [query_hash],
                )
                conn.commit()
                conn.close()
                cached_data = json.loads(result[0])
                cached_data["_confidence"] = 1.0  # 精确匹配置信度 100%
                cached_data["_match_mode"] = "exact"
                logger.info(f"✅ Intent cache HIT (exact): {query[:50]}")
                return cached_data

        elif match_mode == "fuzzy":
            # Tier 1b: 编辑距离模糊匹配（< 100ms for 1000 records）
            all_results = conn.execute(
                "SELECT query_text, result FROM intent_cache ORDER BY created_at DESC LIMIT 1000"
            ).fetchall()

            best_match = None
            best_score = 0.0
            best_cached_query = ""

            for cached_query, cached_result in all_results:
                similarity = self._calculate_similarity(query, cached_query)
                if similarity > best_score:
                    best_score = similarity
                    best_match = cached_result
                    best_cached_query = cached_query

            if best_score >= confidence_threshold:
                conn.close()
                cached_data = json.loads(best_match if isinstance(best_match, str) else '{}')
                cached_data["_confidence"] = best_score
                cached_data["_match_mode"] = "fuzzy"
                cached_data["_cached_query"] = best_cached_query
                logger.info(
                    f"✅ Intent cache HIT (fuzzy, score={best_score:.2f}): {query[:50]} ~ {best_cached_query[:50]}"
                )
                return cached_data

        elif match_mode == "semantic":
            # Tier 1c: Embedding 语义匹配（需要 sentence-transformers）
            conn.close()
            raise NotImplementedError("Semantic cache requires sentence-transformers（未实现）")

        conn.close()
        logger.debug(f"❌ Intent cache MISS ({match_mode}): {query[:50]}")
        return None

    def set_intent(self, query: str, result: dict) -> None:
        """缓存 Intent 结果"""
        query_hash = self._hash(query)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT OR REPLACE INTO intent_cache
               (query_hash, query_text, result)
               VALUES (?, ?, ?)""",
            [query_hash, query, json.dumps(result, ensure_ascii=False)],
        )
        conn.commit()
        conn.close()
        logger.debug(f"📝 Intent cached: {query[:50]}")

    # ==================== 统计 ====================

    def stats(self) -> dict[str, int]:
        """缓存统计"""
        conn = sqlite3.connect(self.db_path)
        stats: dict[str, int] = {
            "blacklist_count": conn.execute("SELECT COUNT(*) FROM guard_blacklist").fetchone()[0],
            "rejected_count": conn.execute("SELECT COUNT(*) FROM guard_rejected").fetchone()[0],
            "intent_count": conn.execute("SELECT COUNT(*) FROM intent_cache").fetchone()[0],
            "rejected_hits": conn.execute("SELECT SUM(hit_count) FROM guard_rejected").fetchone()[0]
            or 0,
            "intent_hits": conn.execute("SELECT SUM(hit_count) FROM intent_cache").fetchone()[0]
            or 0,
        }
        conn.close()
        return stats

    def get_cache_metrics(self) -> dict[str, Any]:
        """获取详细缓存指标，包括命中率"""
        conn = sqlite3.connect(self.db_path)

        # Intent cache metrics
        intent_stats = conn.execute("""
            SELECT
                COUNT(*) as total_entries,
                SUM(hit_count) as total_hits,
                AVG(hit_count) as avg_hits_per_entry,
                MAX(hit_count) as max_hits
            FROM intent_cache
        """).fetchone()

        # Guard rejected metrics
        guard_stats = conn.execute("""
            SELECT
                COUNT(*) as total_rejected,
                SUM(hit_count) as total_hits
            FROM guard_rejected
        """).fetchone()

        # Recent activity (last 24 hours)
        recent_stats = conn.execute("""
            SELECT
                COUNT(*) as recent_queries,
                SUM(hit_count) as recent_hits
            FROM intent_cache
            WHERE datetime(created_at) > datetime('now', '-1 day')
        """).fetchone()

        conn.close()

        # Calculate hit rate
        total_entries = intent_stats[0] or 0
        total_hits = intent_stats[1] or 0
        cache_hit_rate = (
            (total_hits / (total_hits + total_entries)) * 100
            if (total_hits + total_entries) > 0
            else 0
        )

        return {
            "intent": {
                "total_entries": total_entries,
                "total_hits": total_hits,
                "avg_hits_per_entry": round(intent_stats[2] or 0, 2),
                "max_hits": intent_stats[3] or 0,
                "hit_rate_pct": round(cache_hit_rate, 2),
            },
            "guard": {
                "total_rejected": guard_stats[0] or 0,
                "total_hits": guard_stats[1] or 0,
            },
            "recent_24h": {
                "queries": recent_stats[0] or 0,
                "hits": recent_stats[1] or 0,
            },
        }

    def log_cache_metrics(self) -> None:
        """记录缓存指标到日志"""
        metrics = self.get_cache_metrics()
        logger.info(
            f"📊 Cache Metrics: "
            f"Intent={metrics['intent']['total_entries']} entries, "
            f"{metrics['intent']['total_hits']} hits, "
            f"hit_rate={metrics['intent']['hit_rate_pct']}% | "
            f"Guard={metrics['guard']['total_rejected']} rejected | "
            f"Recent 24h: {metrics['recent_24h']['queries']} queries"
        )


# 全局实例
cache = OlavCache()
