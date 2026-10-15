from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class DatosProducto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    precio: Decimal = Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)
    stock: int = Field(ge=0, le=2147483647, strict=True)


class Producto(DatosProducto):
    id: str
    creado_en: datetime
