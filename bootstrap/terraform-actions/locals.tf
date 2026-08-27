# Terraform Actions 역할과 target별 최소 권한을 계산한다.
locals {
  target_state_keys = {
    shared     = "shared/landit-iac/terraform.tfstate"
    develop    = "dev/landit-iac/terraform.tfstate"
    production = "prod/landit-iac/terraform.tfstate"
  }

  role_bindings = {
    for binding in setproduct(["plan", "apply"], keys(local.target_state_keys)) :
    "${binding[0]}-${binding[1]}" => {
      phase  = binding[0]
      target = binding[1]
    }
  }

  platform_read_actions = [
    "athena:GetNamedQuery",
    "athena:GetWorkGroup",
    "athena:ListTagsForResource",
    "ec2:DescribeAvailabilityZones",
    "ec2:DescribeInternetGateways",
    "ec2:DescribeRouteTables",
    "ec2:DescribeSecurityGroups",
    "ec2:DescribeSubnets",
    "ec2:DescribeVpcs",
    "ecr:DescribeRepositories",
    "ecr:GetLifecyclePolicy",
    "ecr:GetRepositoryPolicy",
    "ecr:ListTagsForResource",
    "ecs:DescribeClusters",
    "ecs:DescribeServices",
    "ecs:DescribeTaskDefinition",
    "ecs:ListTagsForResource",
    "elasticloadbalancing:DescribeListeners",
    "elasticloadbalancing:DescribeLoadBalancers",
    "elasticloadbalancing:DescribeRules",
    "elasticloadbalancing:DescribeTags",
    "elasticloadbalancing:DescribeTargetGroups",
    "firehose:DescribeDeliveryStream",
    "firehose:ListTagsForDeliveryStream",
    "glue:GetDatabase",
    "glue:GetTable",
    "glue:GetTags",
    "iam:GetInstanceProfile",
    "iam:GetRole",
    "iam:GetRolePolicy",
    "iam:ListAttachedRolePolicies",
    "iam:ListInstanceProfilesForRole",
    "iam:ListRolePolicies",
    "logs:DescribeLogGroups",
    "logs:DescribeSubscriptionFilters",
    "logs:ListTagsForResource",
    "s3:GetBucketAcl",
    "s3:GetBucketCORS",
    "s3:GetBucketLocation",
    "s3:GetBucketLogging",
    "s3:GetBucketNotification",
    "s3:GetBucketOwnershipControls",
    "s3:GetBucketPolicy",
    "s3:GetBucketPolicyStatus",
    "s3:GetBucketPublicAccessBlock",
    "s3:GetBucketTagging",
    "s3:GetBucketVersioning",
    "s3:GetEncryptionConfiguration",
    "s3:GetLifecycleConfiguration",
    "s3:ListAllMyBuckets",
    "sqs:GetQueueAttributes",
    "sqs:GetQueueUrl",
    "sqs:ListQueueTags",
    "sts:GetCallerIdentity",
    "wafv2:GetLoggingConfiguration",
    "wafv2:GetWebACL",
    "wafv2:GetWebACLForResource",
    "wafv2:ListTagsForResource"
  ]

  read_actions_by_target = {
    shared = [
      "cloudfront:GetDistribution",
      "cloudfront:GetDistributionConfig",
      "cloudfront:GetOriginAccessControl",
      "cloudfront:ListTagsForResource",
      "s3:GetBucketAcl",
      "s3:GetBucketCORS",
      "s3:GetBucketLocation",
      "s3:GetBucketOwnershipControls",
      "s3:GetBucketPolicy",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketTagging",
      "s3:GetBucketVersioning",
      "s3:GetEncryptionConfiguration",
      "s3:ListAllMyBuckets",
      "sts:GetCallerIdentity"
    ]
    develop = concat(local.platform_read_actions, [
      "ec2:DescribeAddresses",
      "ec2:DescribeIamInstanceProfileAssociations",
      "ec2:DescribeInstanceAttribute",
      "ec2:DescribeInstances",
      "ec2:DescribeTags",
      "ec2:DescribeVolumes",
      "ec2:DescribeVolumesModifications",
      "ssm:DescribeDocument",
      "ssm:GetDocument",
      "ssm:ListTagsForResource"
    ])
    production = concat(local.platform_read_actions, [
      "apigateway:GET",
      "lambda:GetFunction",
      "lambda:GetFunctionEventInvokeConfig",
      "lambda:GetPolicy",
      "lambda:ListTags"
    ])
  }

  apply_actions_by_target = {
    shared = []
    develop = [
      "ssm:AddTagsToResource",
      "ssm:RemoveTagsFromResource",
      "ssm:UpdateDocument",
      "ssm:UpdateDocumentDefaultVersion"
    ]
    production = [
      "ecs:UpdateService"
    ]
  }

  apply_resources_by_target = {
    shared = []
    develop = [
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:document/develop-${var.project_name}-ec2-deploy"
    ]
    production = [
      "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:service/prod-${var.project_name}-cluster/prod-${var.project_name}-api"
    ]
  }

  plan_bucket_arn = "arn:aws:s3:::${var.plan_bucket_name}"

  common_tags = {
    Project    = var.project_name
    ManagedBy  = "terraform"
    Repository = var.github_repository
    Purpose    = "terraform-actions-oidc"
  }
}
