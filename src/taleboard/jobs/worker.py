"""
The worker Lambda's entry point: runs the jobs on the generation queue -- generation jobs (see generation_worker) and story imports (see import_worker).

Attributes:
    TOGETHER_KEY_PARAMETER_ENV: str - Environment variable naming the SSM parameter that holds the Together API key.
"""
import logging
import os
import boto3

from taleboard.jobs import generation_worker, import_worker
from taleboard.jobs.queue import message_kind
from taleboard.schema.generation import JobKind

logging.getLogger("taleboard").setLevel(logging.INFO)  # Lambda only shows WARNING+ by default; this surfaces per-call timings

TOGETHER_KEY_PARAMETER_ENV = "TOGETHER_API_KEY_PARAMETER"

def load_together_key() -> None:
    """
    Puts the Together AI API key into the environment (where the Together client looks for it), reading it from SSM Parameter Store.

    Runs once per Lambda container -- warm invocations find the key already set. Does nothing locally, where the key comes from .env instead.
    """
    parameter = os.environ.get(TOGETHER_KEY_PARAMETER_ENV)
    if parameter and "TOGETHER_API_KEY" not in os.environ:
        os.environ["TOGETHER_API_KEY"] = boto3.client("ssm").get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"]

def handler(event: dict, context) -> None:
    """
    Worker Lambda entry point. The queue should deliver one message per invocation (batch size 1).

    Arguments:
        event: dict - SQS event from the generation queue.
        context: LambdaContext - Lambda context, used for the time remaining.
    """
    load_together_key()
    for record in event["Records"]:
        if message_kind(record["body"]) == JobKind.IMPORT:
            import_worker.handle_record(record)
        else:
            generation_worker.handle_record(record, context.get_remaining_time_in_millis)