from pydantic import BaseModel, Field


class ChannelIdentityCreate(BaseModel):
    membership_id: str
    default_unit_code: str = Field(min_length=1, max_length=40)
    channel: str = Field(min_length=1, max_length=30)
    account_key: str = Field(min_length=1, max_length=120)
    external_user_id: str = Field(min_length=1, max_length=180)
    external_chat_id: str | None = Field(default=None, max_length=180)
    display_name: str | None = Field(default=None, max_length=180)


class ChannelIdentityResult(BaseModel):
    id: str
    membership_id: str
    default_unit_code: str
    channel: str
    account_key: str
    external_user_id: str
    external_chat_id: str | None
    display_name: str | None
    active: bool
