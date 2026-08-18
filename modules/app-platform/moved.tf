# 선택적 ECS 플랫폼 전환으로 생긴 인덱스 주소에 기존 리소스 상태를 연결한다.
moved {
  from = aws_security_group.alb
  to   = aws_security_group.alb[0]
}

moved {
  from = aws_security_group.ecs_tasks
  to   = aws_security_group.ecs_tasks[0]
}

moved {
  from = aws_lb.api
  to   = aws_lb.api[0]
}

moved {
  from = aws_lb_target_group.api
  to   = aws_lb_target_group.api[0]
}

moved {
  from = aws_lb_target_group.ai
  to   = aws_lb_target_group.ai[0]
}

moved {
  from = aws_lb_listener.http
  to   = aws_lb_listener.http[0]
}

moved {
  from = aws_iam_role.execution
  to   = aws_iam_role.execution[0]
}

moved {
  from = aws_iam_role_policy_attachment.execution
  to   = aws_iam_role_policy_attachment.execution[0]
}

moved {
  from = aws_iam_role_policy.execution_ssm
  to   = aws_iam_role_policy.execution_ssm[0]
}

moved {
  from = aws_iam_role.api_task
  to   = aws_iam_role.api_task[0]
}

moved {
  from = aws_iam_role.worker_task
  to   = aws_iam_role.worker_task[0]
}

moved {
  from = aws_iam_role_policy.api_task
  to   = aws_iam_role_policy.api_task[0]
}

moved {
  from = aws_iam_role_policy.worker_task
  to   = aws_iam_role_policy.worker_task[0]
}

moved {
  from = aws_ecs_cluster.this
  to   = aws_ecs_cluster.this[0]
}

moved {
  from = aws_ecs_task_definition.api
  to   = aws_ecs_task_definition.api[0]
}

moved {
  from = aws_ecs_task_definition.worker
  to   = aws_ecs_task_definition.worker[0]
}

moved {
  from = aws_ecs_service.api
  to   = aws_ecs_service.api[0]
}

moved {
  from = aws_ecs_service.worker
  to   = aws_ecs_service.worker[0]
}
