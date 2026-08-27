# Terraform Actions 전용 OIDC 역할과 private saved-plan 저장소를 정의한다.
data "aws_caller_identity" "current" {}

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "assume_role" {
  for_each = local.role_bindings

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_owner}/${var.github_repository}:environment:terraform-${each.value.phase}-${each.value.target}"]
    }
  }
}

resource "aws_iam_role" "terraform" {
  for_each = local.role_bindings

  name                 = "${var.project_name}-iac-terraform-${each.value.phase}-${each.value.target}"
  assume_role_policy   = data.aws_iam_policy_document.assume_role[each.key].json
  max_session_duration = 3600
}

resource "aws_s3_bucket" "plans" {
  bucket = var.plan_bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "plans" {
  bucket = aws_s3_bucket.plans.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "plans" {
  bucket = aws_s3_bucket.plans.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "plans" {
  bucket = aws_s3_bucket.plans.id

  rule {
    id     = "expire-terraform-plans"
    status = "Enabled"

    filter {
      prefix = "plans/"
    }

    expiration {
      days = 1
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

data "aws_iam_policy_document" "plans_https_only" {
  statement {
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      local.plan_bucket_arn,
      "${local.plan_bucket_arn}/*"
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "plans_https_only" {
  bucket = aws_s3_bucket.plans.id
  policy = data.aws_iam_policy_document.plans_https_only.json
}

data "aws_iam_policy_document" "terraform" {
  for_each = local.role_bindings

  statement {
    sid       = "ListStateKeys"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.state_bucket_name}"]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = distinct(concat(
        [
          local.target_state_keys[each.value.target],
          "${local.target_state_keys[each.value.target]}.tflock"
        ],
        contains(["develop", "production"], each.value.target) ? [local.target_state_keys.shared] : []
      ))
    }
  }

  statement {
    sid = "ReadTargetState"
    actions = each.value.phase == "apply" ? [
      "s3:GetObject",
      "s3:PutObject"
    ] : ["s3:GetObject"]
    resources = ["arn:aws:s3:::${var.state_bucket_name}/${local.target_state_keys[each.value.target]}"]
  }

  statement {
    sid = "ManageTargetStateLock"
    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject"
    ]
    resources = ["arn:aws:s3:::${var.state_bucket_name}/${local.target_state_keys[each.value.target]}.tflock"]
  }

  dynamic "statement" {
    for_each = contains(["develop", "production"], each.value.target) ? [1] : []
    content {
      sid       = "ReadSharedState"
      actions   = ["s3:GetObject"]
      resources = ["arn:aws:s3:::${var.state_bucket_name}/${local.target_state_keys.shared}"]
    }
  }

  statement {
    sid       = "ListTargetPlans"
    actions   = ["s3:ListBucket"]
    resources = [local.plan_bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["plans/${each.value.target}/*"]
    }
  }

  statement {
    sid       = each.value.phase == "plan" ? "WriteTargetPlan" : "ReadTargetPlan"
    actions   = each.value.phase == "plan" ? ["s3:PutObject"] : ["s3:GetObject"]
    resources = ["${local.plan_bucket_arn}/plans/${each.value.target}/*"]
  }

  statement {
    sid       = "ReadManagedResources"
    actions   = local.read_actions_by_target[each.value.target]
    resources = ["*"]
  }

  dynamic "statement" {
    for_each = each.value.target == "develop" ? [1] : []
    content {
      sid       = "ReadAmazonLinuxAmiParameter"
      actions   = ["ssm:GetParameter"]
      resources = ["arn:aws:ssm:${var.aws_region}::parameter/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"]
    }
  }

  dynamic "statement" {
    for_each = each.value.phase == "apply" && length(local.apply_actions_by_target[each.value.target]) > 0 ? [1] : []
    content {
      sid       = "ManageTargetResources"
      actions   = local.apply_actions_by_target[each.value.target]
      resources = local.apply_resources_by_target[each.value.target]
    }
  }

  dynamic "statement" {
    for_each = each.value.phase == "apply" && each.value.target == "production" ? [1] : []
    content {
      sid = "RegisterProductionTaskDefinitions"
      actions = [
        "ecs:RegisterTaskDefinition",
        "ecs:TagResource"
      ]
      resources = ["*"]

      condition {
        test     = "StringEquals"
        variable = "aws:RequestTag/Project"
        values   = [var.project_name]
      }

      condition {
        test     = "StringEquals"
        variable = "aws:RequestTag/Environment"
        values   = ["prod"]
      }
    }
  }

  dynamic "statement" {
    for_each = each.value.phase == "apply" && each.value.target == "production" ? [1] : []
    content {
      sid     = "PassTargetRuntimeRoles"
      actions = ["iam:PassRole"]
      resources = [
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/prod-${var.project_name}-api-task",
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/prod-${var.project_name}-ecs-execution"
      ]

      condition {
        test     = "StringEquals"
        variable = "iam:PassedToService"
        values   = ["ecs-tasks.amazonaws.com"]
      }
    }
  }
}

resource "aws_iam_role_policy" "terraform" {
  for_each = local.role_bindings

  name   = "${var.project_name}-iac-terraform-${each.value.phase}-${each.value.target}"
  role   = aws_iam_role.terraform[each.key].id
  policy = data.aws_iam_policy_document.terraform[each.key].json
}
