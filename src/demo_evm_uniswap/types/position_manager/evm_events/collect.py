# generated by DipDup 8.0.0b1

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict


class CollectPayload(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    tokenId: int
    recipient: str
    amount0: int
    amount1: int
