"""Base class for API response models."""

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Fields with defaults are always present in responses, so the generated TypeScript marks them required."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
