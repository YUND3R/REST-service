from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class S3StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')
    aws_region: str | None = Field(default=None)
    s3_bucket: str | None = Field(default=None)
    s3_prefix_user_platform_data: str = 'user-platform-data'
    s3_prefix_student_submissions: str = 'student-submissions'
    s3_prefix_model_training: str = 'model-training-data'
    s3_model_training_export_enabled: bool = True

@lru_cache
def get_s3_storage_settings() -> S3StorageSettings:
    return S3StorageSettings()
