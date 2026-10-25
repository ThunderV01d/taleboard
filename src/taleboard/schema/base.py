"""
The base every TaleBoard schema model shares.
"""
from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """
    A Pydantic model whose fields with defaults are still listed as required in the API's response schemas.

    Every response carries every field, defaults included -- so the generated frontend types shouldn't mark them
    optional (an id with a default_factory would otherwise come out as `id?: string`). Request schemas are unaffected.
    """
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)