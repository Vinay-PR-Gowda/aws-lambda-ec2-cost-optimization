import boto3
from datetime import datetime, timedelta, timezone

CPU_THRESHOLD = 5.0      # percent
PERIOD = 300             # seconds (basic monitoring = 5 min)
LOOKBACK_HOURS = 1
MIN_DATAPOINTS = 6       # skip instances without enough history

ec2 = boto3.client("ec2")
cloudwatch = boto3.client("cloudwatch")


def lambda_handler(event, context):
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=LOOKBACK_HOURS)
    stopped = []

    paginator = ec2.get_paginator("describe_instances")
    pages = paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
    )

    for page in pages:
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                instance_id = instance["InstanceId"]

                # Opt-out: tag the instance AutoStop=false to protect it
                tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
                if tags.get("AutoStop", "").lower() == "false":
                    print(f"Skipped (opted out): {instance_id}")
                    continue

                metrics = cloudwatch.get_metric_statistics(
                    Namespace="AWS/EC2",
                    MetricName="CPUUtilization",
                    Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                    StartTime=start,
                    EndTime=end,
                    Period=PERIOD,
                    Statistics=["Average"],
                )

                datapoints = metrics["Datapoints"]
                if len(datapoints) < MIN_DATAPOINTS:
                    print(f"Not enough data for {instance_id}, skipping")
                    continue

                avg_cpu = sum(d["Average"] for d in datapoints) / len(datapoints)
                print(f"{instance_id}: average CPU {avg_cpu:.2f}%")

                if avg_cpu < CPU_THRESHOLD:
                    ec2.stop_instances(InstanceIds=[instance_id])
                    stopped.append(instance_id)
                    print(f"Stopped instance: {instance_id}")

    return {"message": "EC2 Optimization Completed", "stopped": stopped}
