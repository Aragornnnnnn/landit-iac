# AI 저장소의 운영 워크플로에 워커 이미지 조회와 지정 EC2의 SSM 실행만 허용한다.
locals {
  worker_ecr_arn = "arn:aws:ecr:ap-northeast-2:${data.aws_caller_identity.current.account_id}:repository/prod-landit-worker"
}

resource "aws_ssm_document" "deploy_worker" {
  name            = "prod-landit-ec2-deploy-worker"
  document_type   = "Command"
  document_format = "JSON"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Deploy a pinned Landit AI image on the production EC2 host."
    parameters = {
      ImageDigest = {
        type              = "String"
        allowedPattern    = "^sha256:[a-f0-9]{64}$"
        interpolationType = "ENV_VAR"
      }
    }
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "deployWorker"
      inputs = {
        timeoutSeconds = "2400"
        runCommand     = [join("\n", ["#!/bin/sh", "exec python3 - <<'LANDIT_AI_ROLLOUT'", file("${path.module}/rollout/deploy-worker.py"), "LANDIT_AI_ROLLOUT"])]
      }
    }]
  })
}

resource "aws_iam_role" "deploy_worker_on_ec2" {
  name = "landit-github-actions-prod-ec2-deploy-worker"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com" }
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:Aragornnnnnn/landit-ai:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "deploy_worker_on_ec2" {
  name = "landit-prod-ec2-worker-deploy"
  role = aws_iam_role.deploy_worker_on_ec2.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:DescribeImages"]
        Resource = local.worker_ecr_arn
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:SendCommand"]
        Resource = [aws_ssm_document.deploy_worker.arn, aws_instance.app.arn]
      },
      {
        Effect    = "Allow"
        Action    = ["ssm:GetCommandInvocation"]
        Resource  = "*"
        Condition = { StringEquals = { "aws:RequestedRegion" = "ap-northeast-2" } }
      }
    ]
  })
}

output "worker_ec2_deploy_role_arn" {
  description = "AI 저장소의 PROD_WORKER_EC2_ROLE_ARN에 설정할 배포 역할입니다."
  value       = aws_iam_role.deploy_worker_on_ec2.arn
}
