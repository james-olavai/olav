"""Learning system for risk prediction optimization.

Phase 7.3: Learns from past risk assessments to improve risk predictions.

Features:
- Accuracy tracking
- Risk pattern analysis
- Confidence-based predictions
- Recommendation refinement
"""

import logging
from typing import Dict, List, Optional
from statistics import mean

logger = logging.getLogger(__name__)


class RiskPredictionLearner:
    """Learns from risk assessment history to improve predictions.
    
    Tracks how accurate risk predictions have been and adjusts
    confidence and recommendations based on past performance.
    """
    
    def __init__(self, min_samples: int = 10):
        """Initialize learner.
        
        Args:
            min_samples: Minimum samples before making adjustments
        """
        self.min_samples = min_samples
    
    def analyze_risk_history(
        self, risk_records: List[Dict]
    ) -> Dict[str, any]:
        """Analyze risk assessment history.
        
        Args:
            risk_records: List of {estimated_risk_score, actual_risk_occurred}
        
        Returns:
            Analysis dict with accuracy metrics and insights
        """
        if not risk_records or len(risk_records) < self.min_samples:
            return {
                "sufficient_data": False,
                "confidence": 0.0,
                "recommendation": "需要更多数据"
            }
        
        # Categorize by predicted risk level
        high_risk_predictions = [
            r for r in risk_records if r.get("estimated_risk_score", 0) >= 6.0
        ]
        medium_risk_predictions = [
            r for r in risk_records
            if 3.0 <= r.get("estimated_risk_score", 0) < 6.0
        ]
        low_risk_predictions = [
            r for r in risk_records if r.get("estimated_risk_score", 0) < 3.0
        ]
        
        # Calculate accuracy for each category
        high_accuracy = self._calculate_category_accuracy(high_risk_predictions)
        medium_accuracy = self._calculate_category_accuracy(medium_risk_predictions)
        low_accuracy = self._calculate_category_accuracy(low_risk_predictions)
        
        # Overall metrics
        total_accuracy = self._calculate_category_accuracy(risk_records)
        actual_risk_count = sum(
            1 for r in risk_records if r.get("actual_risk_occurred")
        )
        actual_risk_rate = actual_risk_count / len(risk_records) * 100
        
        # Calculate confidence
        confidence = self._calculate_confidence(
            len(risk_records), [high_accuracy, medium_accuracy, low_accuracy]
        )
        
        recommendation = self._get_recommendation(
            confidence, total_accuracy, actual_risk_rate
        )
        
        return {
            "sufficient_data": True,
            "sample_count": len(risk_records),
            "overall_accuracy": total_accuracy,
            "high_risk_accuracy": high_accuracy if high_risk_predictions else None,
            "medium_risk_accuracy": medium_accuracy if medium_risk_predictions else None,
            "low_risk_accuracy": low_accuracy if low_risk_predictions else None,
            "actual_risk_rate": actual_risk_rate,
            "confidence": confidence,
            "recommendation": recommendation
        }
    
    def _calculate_category_accuracy(self, records: List[Dict]) -> Optional[float]:
        """Calculate prediction accuracy for a category.
        
        Args:
            records: List of risk records
        
        Returns:
            Accuracy percentage (0-100) or None if empty
        """
        if not records:
            return None
        
        # For high risk: accuracy = % that actually had risk
        # For low risk: accuracy = % that didn't have risk
        # For medium: mixed
        
        avg_score = mean([r.get("estimated_risk_score", 0) for r in records])
        actual_risk_count = sum(
            1 for r in records if r.get("actual_risk_occurred")
        )
        
        if avg_score >= 6.0:
            # High risk category: should have actual risks
            accuracy = (actual_risk_count / len(records)) * 100
        elif avg_score < 3.0:
            # Low risk category: should NOT have actual risks
            accuracy = ((len(records) - actual_risk_count) / len(records)) * 100
        else:
            # Medium risk: more balanced
            accuracy = (actual_risk_count / len(records)) * 100
        
        return accuracy
    
    def _calculate_confidence(
        self, sample_count: int, category_accuracies: List[Optional[float]]
    ) -> float:
        """Calculate overall confidence in risk model.
        
        Args:
            sample_count: Number of samples
            category_accuracies: List of accuracy percentages for categories
        
        Returns:
            Confidence score (0-1)
        """
        # More samples = higher confidence
        sample_score = min(sample_count / 50.0, 1.0)  # Saturate at 50
        
        # All categories having good accuracy = higher confidence
        valid_accuracies = [a for a in category_accuracies if a is not None]
        
        if valid_accuracies:
            avg_accuracy = mean(valid_accuracies)
            accuracy_score = avg_accuracy / 100.0
        else:
            accuracy_score = 0.0
        
        confidence = (sample_score * 0.5 + accuracy_score * 0.5)
        
        return min(confidence, 1.0)
    
    def _get_recommendation(
        self, confidence: float, accuracy: float, actual_risk_rate: float
    ) -> str:
        """Generate recommendation based on analysis.
        
        Args:
            confidence: Confidence score (0-1)
            accuracy: Overall accuracy percentage
            actual_risk_rate: Percentage of plans that actually had issues
        
        Returns:
            Recommendation string
        """
        if confidence < 0.3:
            return "数据不足，风险预测可靠性低"
        elif accuracy < 50:
            return "风险预测准确性低，建议增加提示和审查"
        elif accuracy < 75:
            return "风险预测需要改进，可考虑调整阈值"
        elif actual_risk_rate > 30:
            return "实际风险率高于预期，应加强审查机制"
        elif actual_risk_rate < 5:
            return "风险管理良好，现有模型表现可靠"
        else:
            return "风险预测基本准确，可继续使用"
    
    def adjust_risk_threshold(
        self, analysis: Dict, current_threshold: float = 6.0
    ) -> Optional[float]:
        """Suggest adjustment to risk classification threshold.
        
        Args:
            analysis: Analysis result
            current_threshold: Current high-risk threshold (0-10)
        
        Returns:
            Adjusted threshold or None if no change recommended
        """
        if not analysis.get("sufficient_data"):
            return None
        
        actual_rate = analysis.get("actual_risk_rate", 0)
        high_accuracy = analysis.get("high_risk_accuracy")
        
        # If high-risk category has low accuracy, lower the threshold
        if high_accuracy is not None and high_accuracy < 60:
            suggested = current_threshold - 0.5
        # If actual risk rate is high, lower threshold to be more cautious
        elif actual_rate > 20:
            suggested = current_threshold - 0.5
        # If high-risk predictions are too frequent, raise threshold
        elif analysis.get("sample_count", 0) > 50 and actual_rate < 5:
            suggested = current_threshold + 0.5
        else:
            return None
        
        # Validate bounds
        suggested = max(1.0, min(9.0, suggested))
        
        # Only suggest if significant change
        if abs(suggested - current_threshold) < 0.3:
            return None
        
        return suggested


def create_risk_learner() -> RiskPredictionLearner:
    """Factory function to create a risk prediction learner.
    
    Returns:
        New RiskPredictionLearner instance
    """
    return RiskPredictionLearner()
