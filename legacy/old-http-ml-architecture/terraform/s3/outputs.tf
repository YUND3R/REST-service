output "bucket_id" {
  description = "Имя бакета"
  value       = aws_s3_bucket.user_data.id
}

output "bucket_arn" {
  description = "ARN бакета для IAM"
  value       = aws_s3_bucket.user_data.arn
}

output "prefix_user_platform_data" {
  description = "Префикс для данных пользователя (платформа, решение задач)"
  value       = "user-platform-data/"
}

output "prefix_student_submissions" {
  description = "Префикс для всех присланных студентами решений"
  value       = "student-submissions/"
}
