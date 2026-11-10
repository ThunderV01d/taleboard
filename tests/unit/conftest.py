"""
Shared fixtures for unit tests that need AWS -- runs against moto's in-memory fakes of DynamoDB, S3 and SQS, so no AWS calls are made and no credentials are needed.

Attributes:
    TABLE: str - Name of the fake DynamoDB table.
    BUCKET: str - Name of the fake S3 bucket.
    QUEUE: str - Name of the fake generation queue (FIFO).
    REGION: str - AWS Region of all three.
"""
import boto3
import pytest
from moto import mock_aws

from taleboard.auth import guest_session
from taleboard.storage.storyboard_store import PROJECTS_INDEX

TABLE = "taleboard-test"
BUCKET = "taleboard-test-images"
QUEUE = "taleboard-test-generation.fifo"
REGION = "eu-west-2"


@pytest.fixture
def aws(monkeypatch):
    """
    Creates a fake table (with the projects index), bucket and generation queue (FIFO), and points the TALEBOARD_* environment variables at them.

    Fake credentials are set so that nothing can ever reach a real AWS account.

    Arguments:
        monkeypatch: pytest.MonkeyPatch - Used to set fake credentials and environment variables.
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
        queue_url = boto3.client("sqs", region_name=REGION).create_queue(QueueName=QUEUE, Attributes={"FifoQueue": "true"})["QueueUrl"]
        monkeypatch.setenv("TALEBOARD_TABLE", TABLE)
        monkeypatch.setenv("TALEBOARD_BUCKET", BUCKET)
        monkeypatch.setenv("TALEBOARD_GENERATION_QUEUE_URL", queue_url)
        monkeypatch.setenv("AWS_REGION", REGION)
        monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)  # Region-less clients (eg:- the worker's SSM client) read this one, not AWS_REGION
        yield


@pytest.fixture
def guest_pool(aws, monkeypatch):
    """
    A fake user pool with the guests group and a guest app client (admin password sign-in only), and the guest's password in a fake secret -- with the Lambda's environment pointed at them.

    Returns:
        dict - The pool's ID ("pool"), the guest client's ID ("client") and the Cognito client ("idp").
    """
    idp = boto3.client("cognito-idp", region_name=REGION)
    pool = idp.create_user_pool(PoolName="users", UsernameAttributes=["email"])["UserPool"]["Id"]
    idp.create_group(UserPoolId=pool, GroupName=guest_session.GUEST_GROUP)
    client = idp.create_user_pool_client(UserPoolId=pool, ClientName="guest", ExplicitAuthFlows=["ALLOW_ADMIN_USER_PASSWORD_AUTH"])["UserPoolClient"]["ClientId"]
    secret = boto3.client("secretsmanager", region_name=REGION).create_secret(Name="guest-password", SecretString="A-long-random-guest-password-1")["ARN"]
    monkeypatch.setenv("TALEBOARD_USER_POOL_ID", pool)
    monkeypatch.setenv("TALEBOARD_GUEST_CLIENT_ID", client)
    monkeypatch.setenv("TALEBOARD_GUEST_SECRET", secret)
    guest_session._cognito.cache_clear()
    guest_session._password.cache_clear()
    yield {"pool": pool, "client": client, "idp": idp}
    guest_session._cognito.cache_clear()
    guest_session._password.cache_clear()
