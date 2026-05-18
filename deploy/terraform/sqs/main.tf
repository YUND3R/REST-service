terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

resource "aws_sqs_queue" "analyze_dlq" {
  name                       = "${var.name_prefix}-analyze-dlq"
  message_retention_seconds  = 1209600
  receive_wait_time_seconds = 0
}

resource "aws_sqs_queue" "analyze_jobs" {
  name                       = "${var.name_prefix}-analyze-jobs"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  receive_wait_time_seconds  = 20
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.analyze_dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue" "generate_dlq" {
  name                       = "${var.name_prefix}-generate-dlq"
  message_retention_seconds  = 1209600
  receive_wait_time_seconds  = 0
}

resource "aws_sqs_queue" "generate_jobs" {
  name                       = "${var.name_prefix}-generate-jobs"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  receive_wait_time_seconds  = 20
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.generate_dlq.arn
    maxReceiveCount     = 5
  })
}
