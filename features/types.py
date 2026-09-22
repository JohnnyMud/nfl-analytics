"""Point-in-time feature value types. Unknown is never null."""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Unknown(BaseModel):
    model_config = ConfigDict(frozen=True)
    reason: str


class Known(BaseModel, Generic[T]):  # noqa: UP046  # frozen Generic[T] as specified
    model_config = ConfigDict(frozen=True)
    value: T


FeatureValue = Known[T] | Unknown
