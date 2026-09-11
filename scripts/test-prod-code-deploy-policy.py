#!/usr/bin/env python3
# 저장 plan의 배포 추가 정책을 AWS IAM 시뮬레이터로 검증하며 AWS 권한은 변경하지 않는다.
import json
from pathlib import Path
import subprocess
import sys


def verify(plan_path):
    plan = json.loads(Path(plan_path).read_text())
    changes = [item for item in plan['resource_changes']
               if item['address'] == 'aws_iam_role_policy.production_code_deploy']
    assert len(changes) == 1, 'Expected one additional deployment policy'
    proposed = changes[0]['change']['after']
    assert proposed['role'] == 'landit-github-actions-prod-deploy'
    policy = proposed['policy']
    region = 'ap-northeast-2'
    account = '982529430654'
    ecs = f'arn:aws:ecs:{region}:{account}:task-definition/'
    ecr = f'arn:aws:ecr:{region}:{account}:repository/'
    iam = f'arn:aws:iam::{account}:role/'
    tasks = [ecs + f'prod-landit-{name}:100' for name in ('api', 'worker')]
    images = [ecr + f'prod-landit-{name}' for name in ('api', 'worker')]
    roles = [iam + 'prod-landit-' + name
             for name in ('ecs-execution', 'api-task', 'worker-task')]
    context = {'aws:RequestedRegion': region, 'aws:RequestTag/Project': 'landit',
               'aws:RequestTag/Environment': 'prod',
               'ecs:CreateAction': 'RegisterTaskDefinition',
               'iam:PassedToService': 'ecs-tasks.amazonaws.com'}
    cases = [
        ('register production', 'ecs:RegisterTaskDefinition', tasks, {}, 'allowed'),
        ('tag on registration', 'ecs:TagResource', tasks, {}, 'allowed'),
        ('pass runtime roles', 'iam:PassRole', roles, {}, 'allowed'),
        ('read digests', 'ecr:DescribeImages', images, {}, 'allowed'),
        ('read task settings', 'ecs:DescribeTaskDefinition', ['*'], {}, 'allowed'),
        ('read task tags', 'ecs:ListTagsForResource', tasks, {}, 'allowed'),
        ('reject other families', 'ecs:RegisterTaskDefinition',
         [ecs + 'develop-landit-api:1', ecs + 'prod-other-api:1'], {}, 'implicitDeny'),
        ('reject other tags', 'ecs:TagResource', [ecs + 'develop-landit-api:1'], {}, 'implicitDeny'),
        ('reject other roles', 'iam:PassRole',
         [iam + 'Administrator', iam + 'develop-landit-ec2-app'], {}, 'implicitDeny'),
        ('reject other repos', 'ecr:DescribeImages', [ecr + 'develop-landit-api'], {}, 'implicitDeny'),
        ('reject other project', 'ecs:RegisterTaskDefinition', tasks,
         {'aws:RequestTag/Project': 'other'}, 'implicitDeny'),
        ('reject missing prod tag', 'ecs:RegisterTaskDefinition', tasks,
         {'aws:RequestTag/Environment': None}, 'implicitDeny'),
        ('reject direct retag', 'ecs:TagResource', tasks, {'ecs:CreateAction': None}, 'implicitDeny'),
        ('reject other service', 'iam:PassRole', roles,
         {'iam:PassedToService': 'lambda.amazonaws.com'}, 'implicitDeny'),
        ('reject other region', 'ecs:DescribeTaskDefinition', ['*'],
         {'aws:RequestedRegion': 'us-east-1'}, 'implicitDeny'),
    ]
    checked = 0
    for label, action, resources, overrides, expected in cases:
        values = context | overrides
        entries = [{'ContextKeyName': key, 'ContextKeyValues': [value],
                    'ContextKeyType': 'string'} for key, value in values.items() if value is not None]
        result = json.loads(subprocess.check_output([
            'aws', '--profile', 'landit', 'iam', 'simulate-custom-policy',
            '--policy-input-list', policy, '--action-names', action,
            '--resource-arns', *resources, '--context-entries', json.dumps(entries),
            '--output', 'json'], text=True))
        evaluations = result['EvaluationResults']
        assert len(evaluations) == 1, label
        evaluation = evaluations[0]
        decisions = evaluation.get('ResourceSpecificResults') or [{
            'EvalResourceName': evaluation['EvalResourceName'],
            'EvalResourceDecision': evaluation['EvalDecision']} ]
        assert {item['EvalResourceName'] for item in decisions} == set(resources), label
        for item in decisions:
            assert item['EvalResourceDecision'] == expected, (label, item['EvalResourceDecision'])
            checked += 1
        print(f'PASS: {label}')
    print(f'{len(cases)} scenarios / {checked} IAM decisions passed; no policies were applied.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: test-prod-code-deploy-policy.py <terraform-show-json>')
    verify(sys.argv[1])
