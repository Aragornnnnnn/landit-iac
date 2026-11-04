# 기존 운영 코드 배포 역할에 이미지 고정 task revision을 등록할 최소 추가 권한을 부여한다.
locals {
  production_task_definition_arns = [
    for service in ["api", "worker"] :
    "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task-definition/prod-${var.project_name}-${service}:*"
  ]
}

data "aws_iam_policy_document" "production_code_deploy" {
  statement {
    sid       = "ReadProductionImageDigests"
    actions   = ["ecr:DescribeImages"]
    resources = [for service in ["api", "worker"] : "arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/prod-${var.project_name}-${service}"]
  }

  statement {
    sid       = "ReadTaskDefinitionSettings"
    actions   = ["ecs:DescribeTaskDefinition"]
    resources = ["*"]
    # DescribeTaskDefinition은 AWS에서 리소스 ARN 제한을 지원하지 않는다.
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }

  statement {
    sid       = "ReadProductionTaskDefinitionTags"
    actions   = ["ecs:ListTagsForResource"]
    resources = local.production_task_definition_arns
  }

  statement {
    sid       = "RegisterProductionTaskRevisions"
    actions   = ["ecs:RegisterTaskDefinition"]
    resources = local.production_task_definition_arns
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

  statement {
    sid       = "TagNewProductionTaskRevisions"
    actions   = ["ecs:TagResource"]
    resources = local.production_task_definition_arns
    condition {
      test     = "StringEquals"
      variable = "ecs:CreateAction"
      values   = ["RegisterTaskDefinition"]
    }
  }

  statement {
    sid     = "PassProductionTaskRoles"
    actions = ["iam:PassRole"]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/prod-${var.project_name}-ecs-execution",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/prod-${var.project_name}-api-task",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/prod-${var.project_name}-worker-task"
    ]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "production_code_deploy" {
  name   = "${var.project_name}-prod-task-revision-deploy"
  role   = "${var.project_name}-github-actions-prod-deploy"
  policy = data.aws_iam_policy_document.production_code_deploy.json
}
