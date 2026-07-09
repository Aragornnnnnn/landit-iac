# 운영 환경의 ECS 기반 application platform module을 호출한다.
module "app_platform" {
  source = "../../modules/app-platform"

  project_name         = var.project_name
  environment          = var.environment
  aws_region           = var.aws_region
  parameter_store_path = var.parameter_store_path

  vpc_cidr            = var.vpc_cidr
  public_subnet_cidrs = var.public_subnet_cidrs

  container_port       = var.container_port
  api_domain_name      = var.api_domain_name
  ai_domain_name       = var.ai_domain_name
  ai_container_port    = var.ai_container_port
  health_check_path    = var.health_check_path
  ai_health_check_path = var.ai_health_check_path

  api_health_check_grace_period_seconds = var.api_health_check_grace_period_seconds
  ai_health_check_grace_period_seconds  = var.ai_health_check_grace_period_seconds

  api_cpu              = var.api_cpu
  api_memory           = var.api_memory
  worker_cpu           = var.worker_cpu
  worker_memory        = var.worker_memory
  api_desired_count    = var.api_desired_count
  worker_desired_count = var.worker_desired_count

  alb_certificate_arn = var.alb_certificate_arn
}
