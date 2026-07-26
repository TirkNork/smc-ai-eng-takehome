from pydantic import BaseModel, Field


class Credentials(BaseModel):
    """Registration body. Login does NOT use this -- it takes two plain
    Form() fields instead of JSON (see routes/auth.py)."""

    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=32)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class User(BaseModel):
    """The public shape of a user -- deliberately has no password_hash field,
    so a hash cannot leak through a response model by accident."""

    id: int
    username: str
