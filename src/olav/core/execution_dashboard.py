"""Dashboard and visualization for execution history and analytics.

Phase 8: Provides visual reports and analytics on execution performance.

Features:
- Execution timeline visualization
- Performance metrics dashboard
- Success/failure statistics  
- Trend analysis charts
- Custom report generation
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Performance metrics for a time period.
    
    Attributes:
        period: Time period (e.g., "daily", "weekly")
        total_executions: Total number of executions
        successful_executions: Successful execution count
        failed_executions: Failed execution count
        success_rate: Percentage of successful executions
        avg_duration: Average execution duration (seconds)
        min_duration: Minimum execution duration
        max_duration: Maximum execution duration
        avg_accuracy: Average estimation accuracy
    """
    period: str
    total_executions: int
    successful_executions: int
    failed_executions: int
    success_rate: float
    avg_duration: float
    min_duration: float
    max_duration: float
    avg_accuracy: float


class ExecutionDashboard:
    """Dashboard for execution analytics and visualization.
    
    Provides:
    - Performance metrics calculation
    - Report generation
    - Trend analysis
    - Visualization data
    """
    
    def __init__(self):
        """Initialize dashboard."""
        self.metrics_cache: Dict[str, PerformanceMetrics] = {}
    
    def calculate_metrics(
        self,
        execution_records: List[Dict],
        period: str = "daily"
    ) -> PerformanceMetrics:
        """Calculate performance metrics for period.
        
        Args:
            execution_records: List of execution records
            period: Time period (daily, weekly, monthly)
        
        Returns:
            PerformanceMetrics object
        """
        if not execution_records:
            return PerformanceMetrics(
                period=period,
                total_executions=0,
                successful_executions=0,
                failed_executions=0,
                success_rate=0.0,
                avg_duration=0.0,
                min_duration=0.0,
                max_duration=0.0,
                avg_accuracy=0.0
            )
        
        total = len(execution_records)
        successful = sum(
            1 for r in execution_records if r.get("status") == "success"
        )
        failed = total - successful
        success_rate = (successful / total * 100) if total > 0 else 0.0
        
        durations = [
            r.get("total_duration", 0)
            for r in execution_records
            if r.get("total_duration") is not None
        ]
        
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        min_duration = min(durations) if durations else 0.0
        max_duration = max(durations) if durations else 0.0
        
        # Calculate average accuracy
        accuracies = [
            r.get("accuracy", 0)
            for r in execution_records
            if r.get("accuracy") is not None
        ]
        avg_accuracy = sum(accuracies) / len(accuracies) if accuracies else 0.0
        
        metrics = PerformanceMetrics(
            period=period,
            total_executions=total,
            successful_executions=successful,
            failed_executions=failed,
            success_rate=success_rate,
            avg_duration=avg_duration,
            min_duration=min_duration,
            max_duration=max_duration,
            avg_accuracy=avg_accuracy
        )
        
        self.metrics_cache[period] = metrics
        return metrics
    
    def generate_performance_report(
        self, metrics: PerformanceMetrics
    ) -> str:
        """Generate markdown performance report.
        
        Args:
            metrics: PerformanceMetrics object
        
        Returns:
            Markdown formatted report
        """
        report = f"""# 📊 性能报告

## {metrics.period.title()} 统计

### 执行概览

| 指标 | 值 |
|------|-----|
| 总执行数 | {metrics.total_executions} |
| 成功 | {metrics.successful_executions} ✅ |
| 失败 | {metrics.failed_executions} ❌ |
| 成功率 | {metrics.success_rate:.1f}% |

### 执行时间

| 指标 | 值 |
|------|-----|
| 平均耗时 | {metrics.avg_duration:.2f}s |
| 最短耗时 | {metrics.min_duration:.2f}s |
| 最长耗时 | {metrics.max_duration:.2f}s |

### 估计准确率

| 指标 | 值 |
|------|-----|
| 平均准确率 | {metrics.avg_accuracy:.1f}% |

## 分析

"""
        # Add insights
        if metrics.success_rate > 95:
            report += "✅ **执行可靠性优秀** - 系统运行稳定\n\n"
        elif metrics.success_rate > 80:
            report += "⚠️  **执行可靠性良好** - 建议关注失败原因\n\n"
        else:
            report += "🔴 **执行可靠性需改进** - 需要深入调查\n\n"
        
        if metrics.avg_accuracy > 85:
            report += "✅ **估计准确性优秀** - 时间估计可信\n\n"
        elif metrics.avg_accuracy > 70:
            report += "⚠️  **估计准确性般** - 建议优化估计模型\n\n"
        else:
            report += "🔴 **估计准确性差** - 需要重新校准\n\n"
        
        return report
    
    def get_trend_data(
        self,
        execution_records: List[Dict],
        days: int = 30
    ) -> Dict[str, List[float]]:
        """Get trend data for visualization.
        
        Args:
            execution_records: List of execution records
            days: Number of days to analyze
        
        Returns:
            Dict with dates and metrics for each day
        """
        # Initialize daily buckets
        daily_data = {}
        for i in range(days):
            date = (datetime.now() - timedelta(days=days - i - 1)).date()
            daily_data[str(date)] = {
                "count": 0,
                "success": 0,
                "duration": 0,
                "accuracy": 0
            }
        
        # Populate data
        for record in execution_records:
            record_date = record.get("date")
            if not record_date:
                continue
            
            date_str = str(record_date)
            if date_str not in daily_data:
                daily_data[date_str] = {
                    "count": 0,
                    "success": 0,
                    "duration": 0,
                    "accuracy": 0
                }
            
            daily_data[date_str]["count"] += 1
            if record.get("status") == "success":
                daily_data[date_str]["success"] += 1
            daily_data[date_str]["duration"] += record.get("total_duration", 0)
            daily_data[date_str]["accuracy"] += record.get("accuracy", 0)
        
        # Calculate averages
        trend_data = {
            "dates": [],
            "success_rates": [],
            "avg_durations": [],
            "avg_accuracies": []
        }
        
        for date_str, data in daily_data.items():
            trend_data["dates"].append(date_str)
            
            if data["count"] > 0:
                success_rate = (data["success"] / data["count"]) * 100
                avg_duration = data["duration"] / data["count"]
                avg_accuracy = data["accuracy"] / data["count"]
            else:
                success_rate = 0.0
                avg_duration = 0.0
                avg_accuracy = 0.0
            
            trend_data["success_rates"].append(success_rate)
            trend_data["avg_durations"].append(avg_duration)
            trend_data["avg_accuracies"].append(avg_accuracy)
        
        return trend_data
    
    def generate_summary_card(
        self, metrics: PerformanceMetrics
    ) -> Dict[str, Any]:
        """Generate summary card data for dashboard.
        
        Args:
            metrics: PerformanceMetrics object
        
        Returns:
            Dictionary with summary data
        """
        status = "healthy" if metrics.success_rate > 95 else \
                 "warning" if metrics.success_rate > 80 else \
                 "critical"
        
        return {
            "title": "执行健康状态",
            "status": status,
            "success_rate": f"{metrics.success_rate:.1f}%",
            "total_executions": metrics.total_executions,
            "avg_duration": f"{metrics.avg_duration:.2f}s",
            "avg_accuracy": f"{metrics.avg_accuracy:.1f}%"
        }


def create_dashboard() -> ExecutionDashboard:
    """Factory function to create dashboard.
    
    Returns:
        New ExecutionDashboard instance
    """
    return ExecutionDashboard()
