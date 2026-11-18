"""机会评分：六因子加权，成本因子反向计分。"""

from decimal import Decimal

from app.schemas.opportunities import OpportunityScoreFactors, OpportunityScoreWeights

_FACTOR_KEYS = (
    "business_value",
    "competitor_gap",
    "material_readiness",
    "implementation_cost",
    "channel_authorization",
    "verifiability",
)


def score_opportunity(
    factors: OpportunityScoreFactors,
    weights: OpportunityScoreWeights,
) -> tuple[dict[str, int], dict[str, float], Decimal]:
    """返回原始因子分、权重和 0–5 的加权优先级分。

    实施成本越高越不利，计算时按 `6 - cost` 反向计分；原始分仍按用户录入值保存。
    """
    raw = factors.model_dump()
    weight_values = weights.model_dump()
    normalized = dict(raw)
    normalized["implementation_cost"] = 6 - raw["implementation_cost"]
    total_weight = sum(weight_values[key] for key in _FACTOR_KEYS)
    weighted = sum(normalized[key] * weight_values[key] for key in _FACTOR_KEYS)
    return raw, weight_values, Decimal(str(round(weighted / total_weight, 2)))
