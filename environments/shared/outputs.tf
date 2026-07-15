# 공유 콘텐츠 bucket과 CloudFront 조회 정보를 출력한다.
output "content_bucket_name" {
  description = "Private S3 bucket used for shared content images."
  value       = aws_s3_bucket.content.bucket
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID for shared content images."
  value       = aws_cloudfront_distribution.content.id
}

output "cloudfront_domain_name" {
  description = "CloudFront default domain used to serve shared content images."
  value       = aws_cloudfront_distribution.content.domain_name
}

output "cloudfront_url" {
  description = "CloudFront base URL used to build content image URLs."
  value       = "https://${aws_cloudfront_distribution.content.domain_name}"
}
