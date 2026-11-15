from decimal import Decimal
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INVEST_", extra="ignore", env_file=".env")
    database_url: SecretStr = Field(
        default=SecretStr("sqlite:///var/development.db"), validation_alias="DATABASE_URL"
    )
    mode: Literal["paper"] = "paper"
    currency: Literal["INR"] = "INR"
    timezone: Literal["Asia/Kolkata"] = "Asia/Kolkata"
    initial_capital: Decimal = Field(default=Decimal("100000.00"), gt=0)
    max_stock_weight: Decimal = Field(default=Decimal("0.08"), gt=0, le=Decimal("0.08"))
    max_sector_weight: Decimal = Field(default=Decimal("0.25"), gt=0, le=Decimal("0.25"))
    max_volume_fraction: Decimal = Field(default=Decimal("0.01"), gt=0, le=Decimal("0.01"))
    max_price_age_hours: int = Field(default=24, ge=1, le=24)
    emergency_stop: bool = True
    market_data_permitted: bool = False
    minimum_daily_turnover: Decimal = Field(default=Decimal("10000000"), ge=0)


def settings() -> Settings:
    return Settings()
