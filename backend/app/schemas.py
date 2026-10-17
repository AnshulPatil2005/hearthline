"""API response and request shapes."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict

from app.models import Role

# Dollar amounts: always exactly two decimal places, in and out.
Money = Annotated[Decimal, AfterValidator(lambda v: v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORM):
    id: int
    name: str
    email: str
    role: Role
    title: str | None
    locale: str
    household_id: int | None


class DemoLoginIn(BaseModel):
    user_id: int


class TokenOut(BaseModel):
    token: str
    user: UserOut
