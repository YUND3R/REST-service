variable "aws_region" {
  type        = string
  description = "Регион AWS для бакета"
}

variable "bucket_name" {
  type        = string
  description = "Глобально уникальное имя S3-бакета"
}

variable "enable_versioning" {
  type        = bool
  default     = false
  description = "Включить версионирование объектов (удобно для аудита, дороже по хранению)"
}

variable "project" {
  type        = string
  default     = "edu-ml"
  description = "Тег для ресурсов"
}

variable "environment" {
  type        = string
  default     = "production"
  description = "Тег окружения (staging/production)"
}
