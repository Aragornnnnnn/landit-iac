# 개발 서버의 SES 발신 도메인과 메일 이벤트 지표, 최소 발송 권한을 정의한다.
resource "aws_sesv2_email_identity" "landit" {
  email_identity = "landit.im"

  dkim_signing_attributes {
    next_signing_key_length = "RSA_2048_BIT"
  }
}

resource "aws_sesv2_configuration_set" "transactional" {
  configuration_set_name = "${local.name_prefix}-transactional"

  reputation_options {
    reputation_metrics_enabled = true
  }

  suppression_options {
    suppressed_reasons = ["BOUNCE", "COMPLAINT"]
  }
}

resource "aws_sesv2_configuration_set_event_destination" "metrics" {
  configuration_set_name = aws_sesv2_configuration_set.transactional.configuration_set_name
  event_destination_name = "delivery-metrics"

  event_destination {
    enabled              = true
    matching_event_types = ["SEND", "DELIVERY", "BOUNCE", "COMPLAINT", "REJECT", "DELIVERY_DELAY"]

    cloud_watch_destination {
      dimension_configuration {
        default_dimension_value = var.environment
        dimension_name          = "Environment"
        dimension_value_source  = "MESSAGE_TAG"
      }
    }
  }
}

output "ses_dkim_records" {
  description = "Vercel DNS에 추가할 SES 도메인 인증 CNAME. 발신 도메인은 이 root에서 한 번만 소유한다."
  value = [for token in aws_sesv2_email_identity.landit.dkim_signing_attributes[0].tokens : {
    name  = "${token}._domainkey.landit.im"
    type  = "CNAME"
    value = "${token}.dkim.amazonses.com"
  }]
}

output "ses_configuration_set" {
  description = "개발 서버의 이메일 전달, 반송 및 불만 CloudWatch 지표 설정."
  value       = aws_sesv2_configuration_set.transactional.configuration_set_name
}
