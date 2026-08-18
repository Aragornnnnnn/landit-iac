#!/usr/bin/env bash
# 개발 EC2 병행 인프라의 보안과 기존 리소스 보존 계약을 검증한다.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULE_OUTPUTS="${ROOT_DIR}/modules/app-platform/outputs.tf"
MODULE_MAIN="${ROOT_DIR}/modules/app-platform/main.tf"
MODULE_VARIABLES="${ROOT_DIR}/modules/app-platform/variables.tf"
for output_name in vpc_id public_subnet_ids api_ecr_repository_arn worker_ecr_repository_arn app_bucket_arn jobs_queue_arn api_log_group_name worker_log_group_name; do
  rg -q "output \"${output_name}\"" "${MODULE_OUTPUTS}"
done

DEV_EC2="${ROOT_DIR}/environments/dev/ec2.tf"
test -f "${DEV_EC2}"
rg -q 'instance_type[[:space:]]*=[[:space:]]*var.dev_ec2_instance_type' "${DEV_EC2}"
rg -q 'default[[:space:]]*=[[:space:]]*"t3.small"' "${ROOT_DIR}/environments/dev/variables.tf"
rg -q 'http_tokens[[:space:]]*=[[:space:]]*"required"' "${DEV_EC2}"
rg -q 'http_put_response_hop_limit[[:space:]]*=[[:space:]]*2' "${DEV_EC2}"
rg -q 'cpu_credits[[:space:]]*=[[:space:]]*"standard"' "${DEV_EC2}"
rg -q 'encrypted[[:space:]]*=[[:space:]]*true' "${DEV_EC2}"
rg -q 'volume_size[[:space:]]*=[[:space:]]*20' "${DEV_EC2}"
rg -q 'associate_public_ip_address[[:space:]]*=[[:space:]]*true' "${DEV_EC2}"
instance_block="$(sed -n '/resource "aws_instance" "app" {/,/^}/p' "${DEV_EC2}")"
for iam_dependency in aws_iam_role_policy_attachment.ec2_ssm_managed_instance aws_iam_role_policy.ec2_app; do
  if ! rg -Fq "${iam_dependency}" <<<"${instance_block}"; then
    echo "계약 위반. EC2 instance는 ${iam_dependency} 완료 뒤에 생성돼야 한다." >&2
    exit 1
  fi
done
if rg -q 'from_port[[:space:]]*=[[:space:]]*22' "${DEV_EC2}"; then
  echo '계약 위반. SSH 22번 포트를 열면 안 된다.' >&2
  exit 1
fi

get_command_invocation_statement="$(sed -n '/actions[[:space:]]*=[[:space:]]*\["ssm:GetCommandInvocation"\]/,/^  }/p' "${DEV_EC2}")"
if ! rg -q 'resources[[:space:]]*=[[:space:]]*\["\*"\]' <<<"${get_command_invocation_statement}"; then
  echo '계약 위반. GitHub deploy role은 GetCommandInvocation만 Resource=*로 허용해야 한다.' >&2
  exit 1
fi
rg -q 'resource "aws_ssm_document" "ec2_deploy"' "${DEV_EC2}"
rg -q 'allowedValues[[:space:]]*=[[:space:]]*\["api", "ai"\]' "${DEV_EC2}"
rg -q 'allowedPattern[[:space:]]*=[[:space:]]*"\^\[0-9a-f\]' "${DEV_EC2}"
rg -q 'interpolationType[[:space:]]*=[[:space:]]*"ENV_VAR"' "${DEV_EC2}"
rg -q 'aws_ssm_document.ec2_deploy.arn' "${DEV_EC2}"
rg -Fq 'parameter${var.parameter_store_path}",' "${DEV_EC2}"
if rg -q 'AWS-RunShellScript' "${DEV_EC2}"; then
  echo '계약 위반. GitHub deploy role은 AWS 관리형 shell 문서를 호출하면 안 된다.' >&2
  exit 1
fi

USER_DATA="${ROOT_DIR}/environments/dev/templates/ec2-user-data.sh.tftpl"
COMPOSE="${ROOT_DIR}/environments/dev/templates/docker-compose.yml.tftpl"
CADDY="${ROOT_DIR}/environments/dev/templates/Caddyfile.tftpl"
test -f "${USER_DATA}"
test -f "${COMPOSE}"
test -f "${CADDY}"
rg -q 'LANDIT_AI_BASE_URL=http://ai:8000' "${USER_DATA}"
rg -q 'chmod 0600' "${USER_DATA}"
rg -q 'flock' "${USER_DATA}"
rg -q 'mkswap' "${USER_DATA}"
rg -q 'amazon-cloudwatch-agent' "${USER_DATA}"
if rg -q 'dnf install[^\n]*[[:space:]]curl([[:space:]]|$)' "${USER_DATA}"; then
  echo '계약 위반. Amazon Linux 2023의 curl-minimal과 충돌하는 curl 패키지를 설치하면 안 된다.' >&2
  exit 1
fi
rg -q '383ce6698cd5d5bbf958d2c8489ed75094e34a77d340404d9f32c4ae9e12baf0' "${USER_DATA}"
rg -q 'sha256sum --check --status' "${USER_DATA}"
rg -q 'wait_for_initial_health api' "${USER_DATA}"
rg -q 'wait_for_initial_health ai' "${USER_DATA}"
rg -q 'grafana_otlp_enabled' "${DEV_EC2}"
rg -q 'grafana_otlp_endpoint' "${DEV_EC2}"
for otel_key in OTEL_EXPORTER_OTLP_METRICS_ENDPOINT MANAGEMENT_OTLP_METRICS_EXPORT_ENABLED MANAGEMENT_OTLP_METRICS_EXPORT_STEP OTEL_METRICS_ENABLED OTEL_EXPORTER_OTLP_PROTOCOL OTEL_EXPORTER_OTLP_ENDPOINT OTEL_SERVICE_NAME OTEL_RESOURCE_ATTRIBUTES; do
  rg -q "${otel_key}" "${USER_DATA}"
done
rg -q 'LANDIT_LOCK_FILE' "${USER_DATA}"
rg -Fq 'if [[ ! -s "$${LANDIT_DIR}/api.tag" ]]' "${USER_DATA}"
rg -Fq "grep -q '^/swapfile swap swap defaults 0 0$' /etc/fstab" "${USER_DATA}"
rg -q 'previous_tag' "${USER_DATA}"
rg -q 'rollback' "${USER_DATA}"
rg -q 'mem_limit: 768m' "${COMPOSE}"
rg -q 'mem_limit: 512m' "${COMPOSE}"
rg -q '127.0.0.1:8080:8080' "${COMPOSE}"
rg -q '127.0.0.1:8000:8000' "${COMPOSE}"
rg -q 'awslogs-group' "${COMPOSE}"
rg -q 'reverse_proxy api:8080' "${CADDY}"
rg -q 'reverse_proxy ai:8000' "${CADDY}"

rg -q 'variable "ecs_platform_enabled"' "${MODULE_VARIABLES}"
rg -q 'ecs_platform_enabled[[:space:]]*=[[:space:]]*false' "${ROOT_DIR}/environments/dev/main.tf"
rg -q 'ignore_changes[[:space:]]*=[[:space:]]*\[ami, user_data\]' "${DEV_EC2}"

for resource_address in \
  'aws_security_group.alb' \
  'aws_security_group.ecs_tasks' \
  'aws_lb.api' \
  'aws_lb_target_group.api' \
  'aws_lb_target_group.ai' \
  'aws_lb_listener.http' \
  'aws_iam_role.execution' \
  'aws_iam_role.api_task' \
  'aws_iam_role.worker_task' \
  'aws_ecs_cluster.this' \
  'aws_ecs_task_definition.api' \
  'aws_ecs_task_definition.worker' \
  'aws_ecs_service.api' \
  'aws_ecs_service.worker'; do
  resource_type="${resource_address%%.*}"
  resource_name="${resource_address#*.}"
  resource_block="$(sed -n "/resource \"${resource_type}\" \"${resource_name}\" {/,/^}/p" "${MODULE_MAIN}")"
  if ! rg -q 'count[[:space:]]*=[[:space:]]*var\.ecs_platform_enabled[[:space:]]*\?[[:space:]]*1[[:space:]]*:[[:space:]]*0' <<<"${resource_block}"; then
    echo "계약 위반. ${resource_address}는 ecs_platform_enabled=false일 때 제거돼야 한다." >&2
    exit 1
  fi
done

CONSOLE_DIR="$(mktemp -d)"
trap 'rm -rf "${CONSOLE_DIR}"' EXIT
rendered_caddy="$(
  printf '%s\n' "templatefile(\"${CADDY}\", { api_domain_names = \"api-ec2-develop.landit.im, api-develop.landit.im\", ai_domain_names = \"ai-ec2-develop.landit.im, ai-develop.landit.im\" })" |
    terraform -chdir="${CONSOLE_DIR}" console
)"
for domain_name in api-ec2-develop.landit.im api-develop.landit.im ai-ec2-develop.landit.im ai-develop.landit.im; do
  if ! rg -Fq "${domain_name}" <<<"${rendered_caddy}"; then
    echo "계약 위반. Caddy render에 ${domain_name}이 포함돼야 한다." >&2
    exit 1
  fi
done
