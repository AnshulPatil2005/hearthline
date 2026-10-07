"""API response and request shapes."""

from pydantic import BaseModel, ConfigDict

from app.models import Role


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
