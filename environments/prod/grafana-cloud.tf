# Grafana Cloud가 Landit AWS 지표를 읽을 공용 IAM 역할을 정의한다.
locals {
  grafana_cloud_aws_account_id = "008923505280"
}

data "aws_iam_policy_document" "grafana_cloud_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.grafana_cloud_aws_account_id}:root"]
    }

    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [var.grafana_cloud_external_id]
    }
  }
}

resource "aws_iam_role" "grafana_cloudwatch" {
  name               = "landit-grafana-cloudwatch-integration"
  description        = "Allow Grafana Cloud to read Landit CloudWatch metrics."
  assume_role_policy = data.aws_iam_policy_document.grafana_cloud_assume_role.json
}

data "aws_iam_policy_document" "grafana_cloudwatch" {
  statement {
    actions = [
      "cloudwatch:GetMetricData",
      "cloudwatch:ListMetrics",
      "tag:GetResources"
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "grafana_cloudwatch" {
  name   = "landit-grafana-cloudwatch-read"
  role   = aws_iam_role.grafana_cloudwatch.id
  policy = data.aws_iam_policy_document.grafana_cloudwatch.json
}
