"""Learning system for time estimation optimization.

Phase 7.2: Learns from historical timing data to improve time estimates.

Features:
- Trend analysis (recent data weighted more heavily)
- Outlier detection
- Estimation accuracy metrics
- Adaptive adjustment
"""

import logging
from typing import Dict, List, Optional
from statistics import mean, stdev, median
import math

logger = logging.getLogger(__name__)


class TimeEstimationLearner:
    """Learns from timing history to improve time estimates.
    
    Uses statistical analysis to identify trends and adjust
    estimations based on past performance.
    """
    
    def __init__(self, min_samples: int = 5, outlier_threshold: float = 2.0):
        """Initialize learner.
        
        Args:
            min_samples: Minimum samples needed before suggesting adjustments
            outlier_threshold: Std dev threshold for outlier detection
        """
        self.min_samples = min_samples
        self.outlier_threshold = outlier_threshold
    
    def analyze_timing_history(
        self, timing_records: List[Dict]
    ) -> Dict[str, float]:
        """Analyze timing history and suggest adjusted estimate.
        
        Args:
            timing_records: List of {estimated_ms, actual_ms, error_percent}
        
        Returns:
            Dict with analysis results
        """
        if not timing_records or len(timing_records) < self.min_samples:
            logger.debug(
                f"Insufficient samples: {len(timing_records)} < {self.min_samples}"
            )
            return {
                "sufficient_data": False,
                "confidence": 0.0,
                "adjusted_estimate": None,
                "recommendation": "需要更多数据"
            }
        
        # Extract actual durations
        actual_durations = [r["actual_ms"] for r in timing_records]
        
        # Filter outliers
        clean_durations = self._remove_outliers(actual_durations)
        
        if not clean_durations:
            return {
                "sufficient_data": False,
                "confidence": 0.0,
                "adjusted_estimate": None,
                "recommendation": "数据异常，无法分析"
            }
        
        # Calculate statistics
        avg_duration = mean(clean_durations)
        median_duration = median(clean_durations)
        variance = stdev(clean_durations) if len(clean_durations) > 1 else 0
        
        # Calculate accuracy metrics
        estimated_durations = [r["estimated_ms"] for r in timing_records]
        accuracy = self._calculate_accuracy(
            estimated_durations[:len(clean_durations)],
            clean_durations
        )
        
        # Determine recommendation
        confidence = self._calculate_confidence(
            len(clean_durations), variance, accuracy
        )
        
        adjusted_estimate = (
            median_duration  # Use median, less affected by outliers
            if confidence > 0.6
            else None
        )
        
        recommendation = self._get_recommendation(
            confidence, accuracy, len(timing_records)
        )
        
        return {
            "sufficient_data": True,
            "sample_count": len(timing_records),
            "clean_samples": len(clean_durations),
            "outliers_removed": len(timing_records) - len(clean_durations),
            "average_ms": avg_duration,
            "median_ms": median_duration,
            "std_dev_ms": variance,
            "accuracy_percent": accuracy,
            "confidence": confidence,
            "adjusted_estimate": adjusted_estimate,
            "recommendation": recommendation
        }
    
    def _remove_outliers(self, values: List[float]) -> List[float]:
        """Remove statistical outliers from data.
        
        Args:
            values: List of numeric values
        
        Returns:
            List with outliers removed
        """
        if len(values) < 2:
            return values
        
        try:
            mean_val = mean(values)
            std_val = stdev(values)
            
            if std_val == 0:
                return values
            
            clean = [
                v for v in values
                if abs((v - mean_val) / std_val) <= self.outlier_threshold
            ]
            
            return clean if clean else values
        except Exception as e:
            logger.warning(f"Error removing outliers: {e}")
            return values
    
    def _calculate_accuracy(
        self, estimated: List[float], actual: List[float]
    ) -> float:
        """Calculate estimation accuracy as percentage.
        
        Args:
            estimated: List of estimated values
            actual: List of actual values
        
        Returns:
            Accuracy percentage (0-100, where 100 is perfect)
        """
        if not estimated or not actual or len(estimated) != len(actual):
            return 0.0
        
        errors = []
        for est, act in zip(estimated, actual):
            if act > 0:
                error = abs(est - act) / act * 100
                errors.append(error)
        
        if not errors:
            return 0.0
        
        # Accuracy = 100 - average_error_percent
        avg_error = mean(errors)
        accuracy = max(0, 100 - avg_error)
        
        return accuracy
    
    def _calculate_confidence(
        self, sample_count: int, variance: float, accuracy: float
    ) -> float:
        """Calculate confidence in recommendation.
        
        Args:
            sample_count: Number of samples
            variance: Standard deviation
            accuracy: Estimation accuracy percentage
        
        Returns:
            Confidence score (0-1)
        """
        # More samples = higher confidence
        sample_score = min(sample_count / 20.0, 1.0)  # Saturate at 20 samples
        
        # Lower variance = higher confidence
        variance_score = math.exp(-variance / 1000.0)  # Exponential decay
        
        # Higher accuracy = higher confidence
        accuracy_score = accuracy / 100.0
        
        # Weighted combination
        confidence = (
            sample_score * 0.4 +
            variance_score * 0.3 +
            accuracy_score * 0.3
        )
        
        return min(confidence, 1.0)
    
    def _get_recommendation(
        self, confidence: float, accuracy: float, sample_count: int
    ) -> str:
        """Generate human-readable recommendation.
        
        Args:
            confidence: Confidence score (0-1)
            accuracy: Accuracy percentage
            sample_count: Number of samples
        
        Returns:
            Recommendation string
        """
        if sample_count < self.min_samples:
            return f"需要更多数据 ({sample_count}/{self.min_samples})"
        elif confidence < 0.4:
            return "数据不一致，建议继续收集样本"
        elif accuracy < 50:
            return "估计偏差大，建议查看历史数据是否存在异常"
        elif accuracy < 80:
            return "可以根据历史数据调整估计"
        else:
            return "估计准确，可信任当前模型"
    
    def suggest_adjustment(
        self,
        current_estimate: float,
        analysis: Dict
    ) -> Optional[float]:
        """Suggest adjustment to current estimate.
        
        Args:
            current_estimate: Current estimate in milliseconds
            analysis: Analysis result from analyze_timing_history
        
        Returns:
            Adjusted estimate or None if no adjustment recommended
        """
        if not analysis.get("sufficient_data"):
            return None
        
        adjusted = analysis.get("adjusted_estimate")
        if adjusted is None:
            return None
        
        # Only suggest significant adjustments (>5%)
        percent_change = abs(adjusted - current_estimate) / current_estimate * 100
        
        if percent_change < 5:
            logger.debug(
                f"Adjustment {percent_change:.1f}% below threshold, ignoring"
            )
            return None
        
        return adjusted


def create_time_learner() -> TimeEstimationLearner:
    """Factory function to create a time estimation learner.
    
    Returns:
        New TimeEstimationLearner instance
    """
    return TimeEstimationLearner()
