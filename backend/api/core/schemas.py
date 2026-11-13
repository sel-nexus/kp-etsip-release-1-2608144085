"""Share strict API identifiers and closed role vocabulary."""
from typing import Annotated, Literal
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

ObjectIdString = Annotated[str, BeforeValidator(str), Field(pattern=r'^[0-9a-fA-F]{24}$')]
RoleName = Literal['Administrator', 'Executive', 'Portfolio Leader', 'Engineer', 'Auditor', 'Read Only']
Permission = Literal['view', 'create', 'edit', 'delete', 'export', 'administer']
class WriteModel(BaseModel):
    """Reject coercion and unrecognized mutation fields."""
    model_config = ConfigDict(extra='forbid', strict=True)
