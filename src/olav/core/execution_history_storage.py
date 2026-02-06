"""Execution history storage for learning system.

Phase 7.1: Stores execution history for analysis and learning by the optimization system.

Features:
- SQLite persistence
- Query execution history
- Timing data collection
- Risk assessment results
- Success/failure tracking
"""

import sqlite3
import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import asdict
import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ExecutionHistoryStorage:
    """Stores and retrieves execution history for learning.
    
    Schema:
    - executions: Plan execution records
    - steps: Individual step execution data
    - timing_data: Time measurements
    - risk_assessments: Risk analysis results
    """
    
    def __init__(self, db_path: str = ".olav/cache/execution_history.db"):
        """Initialize execution history storage.
        
        Args:
            db_path: SQLite database path
        """
        self.db_path = db_path
        self._ensure_db_exists()
    
    def _ensure_db_exists(self) -> None:
        """Create database and tables if they don't exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Execution plans table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    plan_id TEXT PRIMARY KEY,
                    user_intent TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    execution_started TIMESTAMP,
                    execution_ended TIMESTAMP,
                    total_duration REAL,
                    success_count INTEGER,
                    error_count INTEGER,
                    status TEXT
                )
            """)
            
            # Execution steps table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS execution_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id TEXT NOT NULL,
                    step_name TEXT NOT NULL,
                    subagent_name TEXT NOT NULL,
                    step_order INTEGER,
                    status TEXT,
                    actual_duration REAL,
                    estimated_duration REAL,
                    result TEXT,
                    error TEXT,
                    FOREIGN KEY(plan_id) REFERENCES executions(plan_id)
                )
            """)
            
            # Timing data table (for learning time estimates)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS timing_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id TEXT NOT NULL,
                    step_name TEXT NOT NULL,
                    estimated_ms REAL,
                    actual_ms REAL,
                    error_percent REAL,
                    recorded_at TIMESTAMP NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES executions(plan_id)
                )
            """)
            
            # Risk assessments table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS risk_assessments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id TEXT NOT NULL,
                    plan_intent TEXT,
                    estimated_risk_score REAL,
                    actual_risk_occurred BOOLEAN,
                    risk_level TEXT,
                    assessment_date TIMESTAMP NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES executions(plan_id)
                )
            """)
            
            conn.commit()
            logger.info(f"Execution history database initialized: {self.db_path}")
    
    def store_execution(
        self,
        plan_id: str,
        user_intent: str,
        execution_data: Dict[str, Any]
    ) -> None:
        """Store execution plan data.
        
        Args:
            plan_id: Unique plan identifier
            user_intent: User's original query
            execution_data: Dict with execution results
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            now = datetime.datetime.now().isoformat()
            
            cursor.execute("""
                INSERT OR REPLACE INTO executions 
                (plan_id, user_intent, created_at, execution_started, 
                 execution_ended, total_duration, success_count, error_count, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                plan_id,
                user_intent,
                now,
                execution_data.get("execution_started"),
                execution_data.get("execution_ended"),
                execution_data.get("total_duration", 0),
                execution_data.get("success_count", 0),
                execution_data.get("error_count", 0),
                execution_data.get("status", "unknown")
            ))
            
            conn.commit()
            logger.debug(f"Stored execution: {plan_id}")
    
    def store_step_execution(
        self,
        plan_id: str,
        step_name: str,
        step_order: int,
        subagent_name: str,
        actual_duration: float,
        estimated_duration: float,
        status: str,
        result: Optional[Dict] = None,
        error: Optional[str] = None
    ) -> None:
        """Store individual step execution data.
        
        Args:
            plan_id: Plan identifier
            step_name: Name of the step
            step_order: Execution order (0-based)
            subagent_name: Which SubAgent executed
            actual_duration: Actual execution time (seconds)
            estimated_duration: Estimated time (seconds)
            status: Execution status
            result: Optional result data
            error: Optional error message
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO execution_steps
                (plan_id, step_name, subagent_name, step_order, status, 
                 actual_duration, estimated_duration, result, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                plan_id,
                step_name,
                subagent_name,
                step_order,
                status,
                actual_duration,
                estimated_duration,
                json.dumps(result) if result else None,
                error
            ))
            
            # Calculate and store timing data
            if estimated_duration > 0:
                error_percent = abs(
                    (actual_duration - estimated_duration) / estimated_duration * 100
                )
            else:
                error_percent = 0
            
            cursor.execute("""
                INSERT INTO timing_data
                (plan_id, step_name, estimated_ms, actual_ms, error_percent, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                plan_id,
                step_name,
                estimated_duration * 1000,
                actual_duration * 1000,
                error_percent,
                datetime.datetime.now().isoformat()
            ))
            
            conn.commit()
            logger.debug(f"Stored step execution: {plan_id}/{step_name}")
    
    def store_risk_assessment(
        self,
        plan_id: str,
        plan_intent: str,
        estimated_risk_score: float,
        risk_level: str,
        actual_risk_occurred: bool = False
    ) -> None:
        """Store risk assessment data.
        
        Args:
            plan_id: Plan identifier
            plan_intent: User's query
            estimated_risk_score: Estimated risk (0-10)
            risk_level: Risk level (low/medium/high)
            actual_risk_occurred: Whether risk actually occurred
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO risk_assessments
                (plan_id, plan_intent, estimated_risk_score, 
                 actual_risk_occurred, risk_level, assessment_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                plan_id,
                plan_intent,
                estimated_risk_score,
                actual_risk_occurred,
                risk_level,
                datetime.datetime.now().isoformat()
            ))
            
            conn.commit()
            logger.debug(f"Stored risk assessment: {plan_id}")
    
    def get_step_timing_history(self, step_name: str, limit: int = 100) -> List[Dict]:
        """Get historical timing data for a specific step.
        
        Args:
            step_name: Name of the step (e.g., "QUERY", "ANALYZER")
            limit: Maximum number of records to return
        
        Returns:
            List of timing data dictionaries
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT estimated_ms, actual_ms, error_percent, recorded_at
                FROM timing_data
                WHERE step_name = ?
                ORDER BY recorded_at DESC
                LIMIT ?
            """, (step_name, limit))
            
            rows = cursor.fetchall()
            
            return [
                {
                    "estimated_ms": row[0],
                    "actual_ms": row[1],
                    "error_percent": row[2],
                    "recorded_at": row[3]
                }
                for row in rows
            ]
    
    def get_average_step_duration(self, step_name: str) -> Optional[float]:
        """Get average actual duration for a step.
        
        Args:
            step_name: Name of the step
        
        Returns:
            Average duration in milliseconds, or None if no data
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT AVG(actual_ms)
                FROM timing_data
                WHERE step_name = ?
            """, (step_name,))
            
            result = cursor.fetchone()
            return result[0] if result[0] else None
    
    def get_risk_assessments(self, limit: int = 100) -> List[Dict]:
        """Get recent risk assessments.
        
        Args:
            limit: Maximum number of records
        
        Returns:
            List of risk assessment records
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT plan_id, plan_intent, estimated_risk_score, 
                       actual_risk_occurred, risk_level, assessment_date
                FROM risk_assessments
                ORDER BY assessment_date DESC
                LIMIT ?
            """, (limit,))
            
            rows = cursor.fetchall()
            
            return [
                {
                    "plan_id": row[0],
                    "plan_intent": row[1],
                    "estimated_risk_score": row[2],
                    "actual_risk_occurred": row[3],
                    "risk_level": row[4],
                    "assessment_date": row[5]
                }
                for row in rows
            ]
    
    def clear_old_data(self, days: int = 90) -> None:
        """Clear execution history older than specified days.
        
        Args:
            days: Number of days to keep
        """
        cutoff_date = (
            datetime.datetime.now() - datetime.timedelta(days=days)
        ).isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Delete old records
            cursor.execute("DELETE FROM executions WHERE created_at < ?", (cutoff_date,))
            cursor.execute("DELETE FROM timing_data WHERE recorded_at < ?", (cutoff_date,))
            cursor.execute("DELETE FROM risk_assessments WHERE assessment_date < ?", (cutoff_date,))
            
            conn.commit()
            logger.info(f"Cleared execution history older than {days} days")


# Global singleton instance
_storage_instance: Optional[ExecutionHistoryStorage] = None


def get_execution_history_storage() -> ExecutionHistoryStorage:
    """Get or create singleton storage instance.
    
    Returns:
        Shared ExecutionHistoryStorage instance
    """
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = ExecutionHistoryStorage()
    return _storage_instance
