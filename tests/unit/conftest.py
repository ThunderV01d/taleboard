"""
Shared fixtures for unit tests that need AWS -- runs against moto's in-memory fakes of DynamoDB, S3 and SQS, so no AWS calls are made and no credentials are needed.

Attributes:
    TABLE: str - Name of the fake DynamoDB table.
    BUCKET: str - Name of the fake S3 bucket.
    QUEUE: str - Name of the fake SQS queue.
    REGION: str - AWS Region of all three.
"""
import boto3
import pytest
from moto import mock_aws

from taleboard.jobs.queue import JobQueue
from taleboard.storage.project_store import PROJECTS_INDEX, ProjectStore

TABLE = "taleboard-test"
BUCKET = "taleboard-test-images"
QUEUE = "taleboard-test-jobs"
REGION = "eu-west-2"


@pytest.fixture
def aws(monkeypatch):
    """
    Creates a fake table (with the projects index), bucket and queue, and points the TALEBOARD_* environment variables at them.

    Fake credentials are set so that nothing can ever reach a real AWS account.

    Arguments:
        monkeypatch: pytest.MonkeyPatch - Used to set fake credentials and environment variables.

    Returns:
        tuple[ProjectStore,JobQueue] - A store and a queue backed by the fakes.
    """
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    with mock_aws():
        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"} for n in ("PK", "SK", "GSI1PK", "GSI1SK")],
            GlobalSecondaryIndexes=[{
                "IndexName": PROJECTS_INDEX,
                "KeySchema": [{"AttributeName": "GSI1PK", "KeyType": "HASH"}, {"AttributeName": "GSI1SK", "KeyType": "RANGE"}],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
        boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        queue_url = boto3.client("sqs", region_name=REGION).create_queue(QueueName=QUEUE)["QueueUrl"]
        monkeypatch.setenv("TALEBOARD_TABLE", TABLE)
        monkeypatch.setenv("TALEBOARD_BUCKET", BUCKET)
        monkeypatch.setenv("TALEBOARD_QUEUE_URL", queue_url)
        monkeypatch.setenv("AWS_REGION", REGION)
        yield ProjectStore(TABLE, BUCKET, REGION), JobQueue(queue_url, REGION)


@pytest.fixture
def store(aws):
    """
    The fake-backed store.

    Arguments:
        aws: tuple[ProjectStore,JobQueue] - The shared fakes.

    Returns:
        ProjectStore - A store backed by the fakes.
    """
    return aws[0]


@pytest.fixture
def queue(aws):
    """
    The fake-backed queue.

    Arguments:
        aws: tuple[ProjectStore,JobQueue] - The shared fakes.

    Returns:
        JobQueue - A queue backed by the fakes.
    """
    return aws[1]