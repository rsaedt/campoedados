from pydantic import BaseModel, Field


class ChannelAccountCreate(BaseModel):
    channel: str = Field(min_length=1, max_length=30)
    account_key: str = Field(min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=180)
    external_account_id: str | None = Field(default=None, max_length=180)
    credential: str = Field(min_length=1)
    webhook_secret: str = Field(min_length=1)


class ChannelAccountResult(BaseModel):
    id: str
    organization_id: str
    channel: str
    account_key: str
    display_name: str | None
    external_account_id: str | None
    active: bool
    credential_configured: bool = True
