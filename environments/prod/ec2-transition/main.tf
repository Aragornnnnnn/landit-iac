# 운영 EC2와 RDS의 준비 리소스를 기존 ECS와 별도 상태로 관리한다.
terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 7.0"
    }
  }

  backend "s3" {
    bucket              = "landit-terraform-state-944011958218"
    key                 = "prod/landit-iac/ec2-transition.tfstate"
    region              = "ap-northeast-2"
    encrypt             = true
    use_lockfile        = true
    allowed_account_ids = ["944011958218"]
  }
}

provider "aws" {
  region              = "ap-northeast-2"
  allowed_account_ids = ["944011958218"]

  default_tags {
    tags = {
      Project     = "landit"
      Environment = "prod"
      ManagedBy   = "terraform"
      Issue       = "LAN-886"
    }
  }
}

data "aws_caller_identity" "current" {}

data "aws_vpc" "prod" {
  tags = { Name = "prod-landit-vpc" }
}

data "aws_subnet" "public" {
  for_each = toset(["prod-landit-public-0", "prod-landit-public-1"])
  vpc_id   = data.aws_vpc.prod.id
  tags     = { Name = each.key }
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

variable "database_client_ipv4" {
  description = "PostgreSQL 외부 조회를 허용하는 단일 공인 IPv4 CIDR."
  type        = set(string)
  default     = []

  validation {
    condition     = alltrue([for cidr in var.database_client_ipv4 : can(cidrnetmask(cidr)) && endswith(cidr, "/32")])
    error_message = "외부 접속은 IPv4 /32만 허용한다."
  }
}

variable "migration_access_until" {
  description = "EC2에 부여하는 시험 이관용 자격 증명 접근의 UTC 만료 시각."
  type        = string
  default     = null

  validation {
    condition     = var.migration_access_until == null || can(formatdate("YYYY-MM-DD", var.migration_access_until))
    error_message = "만료 시각은 RFC 3339 형식이어야 한다."
  }
}

resource "aws_security_group" "app" {
  name        = "prod-landit-ec2-app"
  description = "Production EC2 application host"
  vpc_id      = data.aws_vpc.prod.id
}

resource "aws_vpc_security_group_egress_rule" "app" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "database" {
  name        = "prod-landit-rds-postgres"
  description = "Production PostgreSQL access"
  vpc_id      = data.aws_vpc.prod.id
}

resource "aws_vpc_security_group_ingress_rule" "database_from_app" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_ingress_rule" "database_from_external_client" {
  for_each          = var.database_client_ipv4
  security_group_id = aws_security_group.database.id
  cidr_ipv4         = each.key
  ip_protocol       = "tcp"
  from_port         = 5432
  to_port           = 5432
}

resource "aws_iam_role" "app" {
  name = "prod-landit-ec2-app"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "session_manager" {
  name = "landit-ec2-session-manager-transport"
  role = aws_iam_role.app.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Resource = "*"
      Action = [
        "ssm:DescribeAssociation",
        "ssm:GetDeployablePatchSnapshotForInstance",
        "ssm:GetDocument",
        "ssm:DescribeDocument",
        "ssm:GetManifest",
        "ssm:ListAssociations",
        "ssm:ListInstanceAssociations",
        "ssm:PutInventory",
        "ssm:PutComplianceItems",
        "ssm:PutConfigurePackageResult",
        "ssm:UpdateAssociationStatus",
        "ssm:UpdateInstanceAssociationStatus",
        "ssm:UpdateInstanceInformation",
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel",
        "ec2messages:AcknowledgeMessage",
        "ec2messages:DeleteMessage",
        "ec2messages:FailMessage",
        "ec2messages:GetEndpoint",
        "ec2messages:GetMessages",
        "ec2messages:SendReply",
      ]
    }]
  })
}

resource "aws_iam_instance_profile" "app" {
  name = aws_iam_role.app.name
  role = aws_iam_role.app.name
}

resource "aws_iam_role_policy" "ecr_pull" {
  name = "pull-landit-production-images"
  role = aws_iam_role.app.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
        Resource = [
          "arn:aws:ecr:ap-northeast-2:${data.aws_caller_identity.current.account_id}:repository/prod-landit-api",
          "arn:aws:ecr:ap-northeast-2:${data.aws_caller_identity.current.account_id}:repository/prod-landit-worker",
        ]
      },
    ]
  })
}

resource "aws_instance" "app" {
  ami                         = nonsensitive(data.aws_ssm_parameter.al2023.value)
  instance_type               = "t3.medium"
  subnet_id                   = data.aws_subnet.public["prod-landit-public-0"].id
  vpc_security_group_ids      = [aws_security_group.app.id]
  iam_instance_profile        = aws_iam_instance_profile.app.name
  associate_public_ip_address = true
  user_data                   = file("${path.module}/bootstrap.sh")

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
  }

  tags = { Name = "prod-landit-ec2-app" }

  lifecycle {
    # 외부 접속 IP 변경 시 최신 AMI 공개로 운영 호스트가 교체되지 않도록 한다.
    ignore_changes = [ami]
  }

  depends_on = [aws_iam_role_policy.session_manager, aws_vpc_security_group_egress_rule.app]
}

resource "aws_eip" "app" {
  domain = "vpc"
  tags   = { Name = "prod-landit-ec2-app" }
}

resource "aws_eip_association" "app" {
  allocation_id = aws_eip.app.id
  instance_id   = aws_instance.app.id
}

resource "aws_db_subnet_group" "app" {
  name       = "prod-landit-rds-postgres"
  subnet_ids = [for subnet in data.aws_subnet.public : subnet.id]
}

resource "aws_db_instance" "app" {
  identifier                  = "prod-landit-postgres"
  engine                      = "postgres"
  engine_version              = "17.11"
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  storage_type                = "gp3"
  storage_encrypted           = true
  db_name                     = "landit"
  username                    = "landit_admin"
  manage_master_user_password = true
  publicly_accessible         = true
  multi_az                    = false
  availability_zone           = data.aws_subnet.public["prod-landit-public-0"].availability_zone
  db_subnet_group_name        = aws_db_subnet_group.app.name
  vpc_security_group_ids      = [aws_security_group.database.id]
  backup_retention_period     = 7
  deletion_protection         = true
  final_snapshot_identifier   = "prod-landit-postgres-final"
  copy_tags_to_snapshot       = true
}

resource "aws_iam_role_policy" "migration_access" {
  count = var.migration_access_until == null ? 0 : 1
  name  = "rehearse-postgres-migration"
  role  = aws_iam_role.app.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "ssm:GetParameters"
        Resource = [
          for name in ["DB_URL", "DB_USERNAME", "DB_PASSWORD"] :
          "arn:aws:ssm:ap-northeast-2:${data.aws_caller_identity.current.account_id}:parameter/landit/prod/${name}"
        ]
        Condition = { DateLessThan = { "aws:CurrentTime" = var.migration_access_until } }
      },
      {
        Effect    = "Allow"
        Action    = "secretsmanager:GetSecretValue"
        Resource  = aws_db_instance.app.master_user_secret[0].secret_arn
        Condition = { DateLessThan = { "aws:CurrentTime" = var.migration_access_until } }
      },
    ]
  })
}

output "instance_id" {
  value       = aws_instance.app.id
  description = "SSM 대상 운영 EC2 인스턴스 ID."
}

output "database_address" {
  value       = aws_db_instance.app.address
  description = "운영 PostgreSQL DNS 이름."
}

output "app_ipv4" {
  value       = aws_eip.app.public_ip
  description = "트래픽 전환 시 사용할 운영 EC2 공인 IPv4."
}
