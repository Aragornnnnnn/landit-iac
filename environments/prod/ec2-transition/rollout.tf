# GitHub Actions가 지정된 운영 EC2에만 다이제스트 기반 배포를 요청하도록 허용한다.
resource "aws_ssm_document" "deploy_api" {
  name            = "prod-landit-ec2-deploy-api"
  document_type   = "Command"
  document_format = "JSON"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Roll out a pinned Landit BE image on the production EC2 host."
    parameters = {
      ImageDigest = {
        type              = "String"
        allowedPattern    = "^sha256:[a-f0-9]{64}$"
        interpolationType = "ENV_VAR"
      }
    }
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "blueGreenApi"
      inputs = {
        timeoutSeconds = "1800"
        runCommand     = [file("${path.module}/rollout/deploy-api.sh")]
      }
    }]
  })
}

resource "aws_iam_role_policy" "deploy_api_on_ec2" {
  name = "landit-prod-ec2-api-deploy"
  role = "landit-github-actions-prod-deploy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:SendCommand"]
        Resource = [aws_ssm_document.deploy_api.arn, aws_instance.app.arn]
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
