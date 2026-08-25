# 개발 ECS 플랫폼과 병행할 단일 EC2 실행 경로와 최소 권한을 정의한다.
data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_caller_identity" "current" {}

data "aws_iam_role" "github_actions_deploy" {
  name = "landit-github-actions-develop-deploy"
}

locals {
  ec2_runtime_env = templatefile("${path.module}/templates/ec2-runtime-env.sh.tftpl", {
    aws_region             = var.aws_region
    parameter_store_path   = var.parameter_store_path
    environment            = var.environment
    app_bucket_name        = module.app_platform.app_bucket_name
    content_bucket_name    = data.terraform_remote_state.shared.outputs.content_bucket_name
    content_cloudfront_url = data.terraform_remote_state.shared.outputs.cloudfront_url
    jobs_queue_url         = module.app_platform.jobs_queue_url
    grafana_otlp_enabled   = tostring(var.grafana_otlp_enabled)
    grafana_otlp_endpoint  = var.grafana_otlp_endpoint
  })
}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2_app" {
  name               = "${local.name_prefix}-ec2-app"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_instance_profile" "ec2_app" {
  name = "${local.name_prefix}-ec2-app"
  role = aws_iam_role.ec2_app.name
}

resource "aws_iam_role_policy_attachment" "ec2_ssm_managed_instance" {
  role       = aws_iam_role.ec2_app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "ec2_app" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer"
    ]
    resources = [
      module.app_platform.api_ecr_repository_arn,
      module.app_platform.worker_ecr_repository_arn
    ]
  }

  statement {
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath"
    ]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.parameter_store_path}",
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.parameter_store_path}/*"
    ]
  }

  statement {
    actions   = ["kms:Decrypt"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.aws_region}.amazonaws.com"]
    }
  }

  statement {
    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject"
    ]
    resources = ["${module.app_platform.app_bucket_arn}/*"]
  }

  statement {
    actions   = ["s3:ListBucket"]
    resources = [module.app_platform.app_bucket_arn]
  }

  statement {
    actions = ["s3:PutObject"]
    resources = [
      "arn:aws:s3:::${data.terraform_remote_state.shared.outputs.content_bucket_name}/content/inbox/*"
    ]
  }

  statement {
    actions = [
      "sqs:ChangeMessageVisibility",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
      "sqs:ReceiveMessage",
      "sqs:SendMessage"
    ]
    resources = [module.app_platform.jobs_queue_arn]
  }

  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "${module.app_platform.api_log_group_arn}:*",
      "${module.app_platform.worker_log_group_arn}:*"
    ]
  }

  statement {
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["Landit/EC2"]
    }
  }
}

resource "aws_iam_role_policy" "ec2_app" {
  name   = "${local.name_prefix}-ec2-app"
  role   = aws_iam_role.ec2_app.id
  policy = data.aws_iam_policy_document.ec2_app.json
}

resource "aws_security_group" "ec2_app" {
  name        = "${local.name_prefix}-ec2-app"
  description = "Allow public HTTP and HTTPS traffic to the EC2 application."
  vpc_id      = module.app_platform.vpc_id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "app" {
  depends_on = [
    aws_iam_role_policy_attachment.ec2_ssm_managed_instance,
    aws_iam_role_policy.ec2_app
  ]

  ami                         = data.aws_ssm_parameter.al2023_ami.value
  instance_type               = var.dev_ec2_instance_type
  subnet_id                   = module.app_platform.public_subnet_ids[0]
  vpc_security_group_ids      = [aws_security_group.ec2_app.id]
  iam_instance_profile        = aws_iam_instance_profile.ec2_app.name
  associate_public_ip_address = true
  user_data = templatefile("${path.module}/templates/ec2-user-data.sh.tftpl", {
    api_image            = module.app_platform.api_ecr_repository_url
    ai_image             = module.app_platform.worker_ecr_repository_url
    api_log_group_name   = module.app_platform.api_log_group_name
    ai_log_group_name    = module.app_platform.worker_log_group_name
    aws_region           = var.aws_region
    parameter_store_path = var.parameter_store_path
    ecr_registry         = split("/", module.app_platform.api_ecr_repository_url)[0]
    runtime_env          = local.ec2_runtime_env
    docker_compose = templatefile("${path.module}/templates/docker-compose.yml.tftpl", {
      api_log_group_name = module.app_platform.api_log_group_name
      ai_log_group_name  = module.app_platform.worker_log_group_name
      aws_region         = var.aws_region
    })
    caddyfile = templatefile("${path.module}/templates/Caddyfile.tftpl", {
      api_domain_names = "${var.api_ec2_domain_name}, ${var.api_domain_name}"
      ai_domain_names  = "${var.ai_ec2_domain_name}, ${var.ai_domain_name}"
    })
  })

  credit_specification {
    cpu_credits = "standard"
  }

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = 20
  }

  tags = {
    Name = "${local.name_prefix}-ec2-app"
  }

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}

resource "aws_eip" "app" {
  domain = "vpc"
}

resource "aws_eip_association" "app" {
  allocation_id = aws_eip.app.id
  instance_id   = aws_instance.app.id
}

resource "aws_ssm_document" "ec2_deploy" {
  name          = "${local.name_prefix}-ec2-deploy"
  document_type = "Command"

  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Deploy one validated Landit service image to the develop EC2 instance."
    parameters = {
      service = {
        type              = "String"
        allowedValues     = ["api", "ai"]
        interpolationType = "ENV_VAR"
      }
      imageSha = {
        type              = "String"
        allowedPattern    = "^[0-9a-f]{40}$"
        interpolationType = "ENV_VAR"
      }
    }
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "deployService"
      precondition = {
        StringEquals = ["platformType", "Linux"]
      }
      inputs = {
        runCommand = [
          "runtime_env_file=\"$(mktemp /opt/landit/bin/runtime-env.XXXXXX)\"",
          "trap 'rm -f \"$runtime_env_file\"' EXIT",
          "printf '%s' '${base64encode(local.ec2_runtime_env)}' | base64 --decode > \"$runtime_env_file\"",
          "chmod 0750 \"$runtime_env_file\"",
          "mv \"$runtime_env_file\" /opt/landit/bin/runtime-env",
          "/opt/landit/bin/deploy-service \"$SSM_service\" \"$SSM_imageSha\""
        ]
      }
    }]
  })
}

data "aws_iam_policy_document" "github_actions_ec2_deploy" {
  statement {
    actions = ["ssm:SendCommand"]
    resources = [
      aws_instance.app.arn,
      aws_ssm_document.ec2_deploy.arn
    ]
  }

  statement {
    actions   = ["ssm:GetCommandInvocation"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_actions_ec2_deploy" {
  name   = "develop-ec2-send-command"
  role   = data.aws_iam_role.github_actions_deploy.id
  policy = data.aws_iam_policy_document.github_actions_ec2_deploy.json
}
