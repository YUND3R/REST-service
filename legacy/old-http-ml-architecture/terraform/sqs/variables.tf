variable "aws_region" {
  type        = string
  description = "Регион AWS"
}

variable "name_prefix" {
  type        = string
  default     = "edu-ml"
  description = "Префикс имён очередей"
}

variable "visibility_timeout_seconds" {
  type        = number
  default     = 900
  description = "Должно быть >= максимального времени инференса на сообщение"
}
