from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./simple_contester.db"
    jwt_secret: str = "dev-secret"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 24
    login_rate_limit_enabled: bool = True
    login_rate_limit_attempts: int = 8
    login_rate_limit_window_seconds: int = 60
    login_rate_limit_lockout_seconds: int = 300
    admin_username: str = "admin"
    admin_password: str = "admin"
    cors_origins: str = "http://localhost:5173"
    site_timezone: str = "Asia/Krasnoyarsk"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
