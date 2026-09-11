#!/usr/bin/env python3
# 운영 실행 이미지와 배포 기준을 읽어 Terraform 고정 입력과 apply 직전 검증에 사용한다.
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def aws(*args):
    return json.loads(subprocess.check_output(["aws", *args, "--output", "json"], text=True))


def snapshot(cluster="prod-landit-cluster", prefix="prod-landit"):
    baseline = {}
    for container in ("api", "worker"):
        name = f"{prefix}-{container}"
        response = aws("ecs", "describe-services", "--cluster", cluster, "--services", name)
        services = response.get("services", [])
        if response.get("failures") or len(services) != 1:
            raise ValueError(f"{name}: service is unavailable")
        service = services[0]
        deployments = service.get("deployments", [])
        if (len(deployments) != 1 or deployments[0].get("rolloutState") != "COMPLETED"
                or service.get("pendingCount") != 0 or service.get("desiredCount", 0) < 1
                or service["runningCount"] != service["desiredCount"]):
            raise ValueError(f"{name}: finish application deployment before planning infrastructure")
        task_arns = aws("ecs", "list-tasks", "--cluster", cluster, "--service-name", name,
                        "--desired-status", "RUNNING")["taskArns"]
        if len(task_arns) != service["desiredCount"] or len(task_arns) > 100:
            raise ValueError(f"{name}: running tasks changed while capturing images")
        tasks_response = aws("ecs", "describe-tasks", "--cluster", cluster, "--tasks", *task_arns)
        tasks = tasks_response.get("tasks", [])
        if tasks_response.get("failures") or len(tasks) != len(task_arns):
            raise ValueError(f"{name}: not every running task could be inspected")
        images = set()
        for task in tasks:
            if task.get("lastStatus") != "RUNNING" or task.get("taskDefinitionArn") != service["taskDefinition"]:
                raise ValueError(f"{name}: mixed task revisions are running")
            containers = [c for c in task["containers"] if c["name"] == container]
            if len(containers) != 1:
                raise ValueError(f"{name}: expected application container is missing")
            current = containers[0]
            digest = current.get("imageDigest", "")
            repository = re.split(r"[:@]", current["image"])[0]
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError(f"{name}: runtime digest is unavailable")
            if not re.fullmatch(r"[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/" + re.escape(name), repository):
                raise ValueError(f"{name}: unexpected application repository")
            images.add(f"{repository}@{digest}")
        if len(images) != 1:
            raise ValueError(f"{name}: mixed image digests are running")
        baseline[container] = {
            "image_ref": images.pop(),
            "task_definition": service["taskDefinition"],
            "deployment_id": deployments[0]["id"],
            "task_arns": sorted(task_arns),
        }
        after = aws("ecs", "describe-services", "--cluster", cluster, "--services", name)
        if after.get("failures") or after.get("services", [{}])[0].get("deployments") != deployments:
            raise ValueError(f"{name}: deployment changed while capturing images")
    return baseline


def inputs(baseline):
    return {"api_image_ref": baseline["api"]["image_ref"],
            "worker_image_ref": baseline["worker"]["image_ref"],
            "release_baseline": baseline}


def verify(plan, current):
    variables = plan.get("variables", {})
    expected = variables.get("release_baseline", {}).get("value")
    if expected != current:
        raise ValueError("Application deployment changed after plan; create and review a new plan")
    for name in ("api_image_ref", "worker_image_ref"):
        if variables.get(name, {}).get("value") != inputs(current)[name]:
            raise ValueError("Plan image does not match the approved running image")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write private Terraform variable JSON")
    parser.add_argument("--check", action="store_true", help="Read terraform show -json from stdin")
    args = parser.parse_args()
    if bool(args.output) == args.check:
        parser.error("Choose --output or --check")
    try:
        current = snapshot()
        if args.check:
            verify(json.load(sys.stdin), current)
            print("Application revisions and digests still match the saved plan.")
        else:
            with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
                json.dump(inputs(current), stream, indent=2)
                stream.write("\n")
            print("Captured stable application digests for the infrastructure plan.")
    except (ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Image preservation check failed: {error}\n")


if __name__ == "__main__":
    main()
