from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Transaction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    amount: float = Field(gt=0, le=1e12, allow_inf_nan=False)
    location: str = Field(min_length=1, max_length=256)
    timestamp: str = Field(min_length=1, max_length=64)
    merchant: str = Field(min_length=1, max_length=256)


class MerchantReputationResult(BaseModel):
    title: str
    snippet: str
    url: str
    source_domain: str


class MerchantReputation(BaseModel):
    merchant: str
    score: Optional[int] = None
    mode: Literal["scored", "unknown", "disabled", "timeout", "error"]
    signals: list[str] = Field(default_factory=list)
    top_results: list[MerchantReputationResult] = Field(default_factory=list)
    cached: bool = False
