output "sqs_analyze_queue_url" {
  value       = aws_sqs_queue.analyze_jobs.url
  description = "SQS_ANALYZE_QUEUE_URL"
}

output "sqs_generate_queue_url" {
  value       = aws_sqs_queue.generate_jobs.url
  description = "SQS_GENERATE_QUEUE_URL"
}

output "sqs_analyze_dlq_url" {
  value = aws_sqs_queue.analyze_dlq.url
}

output "sqs_generate_dlq_url" {
  value = aws_sqs_queue.generate_dlq.url
}
