"""Stops the GPU instance before its running hours can break the monthly spending limit.

AWS Budgets reports with a delay of many hours, too late to stop a machine that
costs money every hour. This runs in AWS every few minutes, whether or not any
other machine is on, and counts the hours itself. It never starts anything.
"""
import datetime
import json
import os

import boto3

TAG = os.environ.get('TAG_VALUE', 'deal-gpu')
TOPIC = os.environ['TOPIC_ARN']
MAX_MONTH_HOURS = float(os.environ.get('MAX_MONTH_HOURS', '32'))
MAX_SESSION_HOURS = float(os.environ.get('MAX_SESSION_HOURS', '6'))
TICK_MINUTES = float(os.environ.get('TICK_MINUTES', '5'))
ALERT_PERCENTS = (50, 80, 100)

ec2, ssm, sns = boto3.client('ec2'), boto3.client('ssm'), boto3.client('sns')


def _read(name, default):
    try:
        return ssm.get_parameter(Name=name)['Parameter']['Value']
    except ssm.exceptions.ParameterNotFound:
        return default


def _write(name, value):
    ssm.put_parameter(Name=name, Value=str(value), Type='String', Overwrite=True)


def _instances():
    pages = ec2.describe_instances(Filters=[{'Name': 'tag:Project', 'Values': [TAG]},
                                            {'Name': 'instance-state-name', 'Values': ['pending', 'running']}])
    return [item for reservation in pages['Reservations'] for item in reservation['Instances']]


def _tell(subject, text):
    sns.publish(TopicArn=TOPIC, Subject=subject[:100], Message=text)


def handler(event, context):
    now = datetime.datetime.now(datetime.timezone.utc)
    month = now.strftime('%Y-%m')
    hours_name, alerted_name = f'/deal-gpu/hours/{month}', f'/deal-gpu/alerted/{month}'
    hours = float(_read(hours_name, '0'))
    instances = _instances()
    if instances:
        hours += len(instances) * TICK_MINUTES / 60
        _write(hours_name, round(hours, 3))
    alerted = json.loads(_read(alerted_name, '[]'))
    for percent in ALERT_PERCENTS:
        if percent not in alerted and hours >= MAX_MONTH_HOURS * percent / 100:
            alerted.append(percent)
            _write(alerted_name, json.dumps(alerted))
            _tell(f'GPU hours at {percent}% of the monthly limit', f'{hours:.1f} of {MAX_MONTH_HOURS:g} GPU hours used in {month}.')
    too_long = [item['InstanceId'] for item in instances
                if (now - item['LaunchTime']).total_seconds() / 3600 >= MAX_SESSION_HOURS]
    over = hours >= MAX_MONTH_HOURS
    stopping = [item['InstanceId'] for item in instances] if over else too_long
    if stopping:
        ec2.stop_instances(InstanceIds=stopping)
        why = f'the monthly limit of {MAX_MONTH_HOURS:g} hours was reached' if over else f'it ran for {MAX_SESSION_HOURS:g} hours in one session'
        _tell('GPU instance stopped by the spending guard', f'Stopped {", ".join(stopping)} because {why}.')
    return {'hours': hours, 'running': len(instances), 'stopped': stopping}
