"""
CDK stack for the TaleBoard backend: storage, the job queue, and the API, worker and dead-letter Lambdas.

Attributes:
    REPO_ROOT: Path - Repository root, the worker image's build context.
    SRC_DIR: Path - Source folder bundled into the API and dead-letter Lambdas (with src/requirements.txt).
    PROJECTS_INDEX: str - Name of the sparse project-listing GSI (must match taleboard.storage.project_store).
    TOGETHER_KEY_PARAMETER: str - Name of the SSM SecureString holding the Together AI API key (created by hand).
    API_KEY_PARAMETER: str - Name of the SSM SecureString holding the API's shared key (created by hand).
    MAX_ATTEMPTS: int - Deliveries before a job is dead-lettered (must match taleboard.jobs.worker.MAX_ATTEMPTS).
    HAIKU_PROFILE_ID: str - Bedrock EU cross-region inference profile used by the story breakdown.
    HAIKU_MODEL_ID: str - Foundation model behind that profile.
"""
from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as event_sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_ssm as ssm
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from aws_cdk.aws_lambda_python_alpha import BundlingOptions, PythonFunction
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
PROJECTS_INDEX = "projects-by-created-at"
TOGETHER_KEY_PARAMETER = "/taleboard/together-api-key"
API_KEY_PARAMETER = "/taleboard/api-key"
MAX_ATTEMPTS = 5
HAIKU_PROFILE_ID = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
HAIKU_MODEL_ID = "anthropic.claude-haiku-4-5-20251001-v1:0"


class TaleboardStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # Comma-separated, so the deployed frontend and local development (npm run dev) can both be allowed
        cors_origins = [origin.strip() for origin in (self.node.try_get_context("corsOrigin") or "*").split(",") if origin.strip()]
        alarm_email = self.node.try_get_context("alarmEmail")

        # Storage
        table = dynamodb.Table(
            self, "Table",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )
        table.add_global_secondary_index(
            index_name=PROJECTS_INDEX,
            partition_key=dynamodb.Attribute(name="GSI1PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="GSI1SK", type=dynamodb.AttributeType.STRING),
        )
        bucket = s3.Bucket(
            self, "Images",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Job queue -- visibility outlasts the worker's 15-minute timeout, and matches the 16-minute job lease
        dead_letters = sqs.Queue(self, "DeadLetters", retention_period=Duration.days(14), enforce_ssl=True)        
        jobs = sqs.Queue(
            self, "Jobs",
            visibility_timeout=Duration.minutes(16),
            dead_letter_queue=sqs.DeadLetterQueue(queue=dead_letters, max_receive_count=MAX_ATTEMPTS),
            enforce_ssl=True,
        )

        together_key = ssm.StringParameter.from_secure_string_parameter_attributes(
            self, "TogetherKey", parameter_name=TOGETHER_KEY_PARAMETER
        )
        api_key = ssm.StringParameter.from_secure_string_parameter_attributes(
            self, "ApiKey", parameter_name=API_KEY_PARAMETER
        )
        storage_env = {"TALEBOARD_TABLE": table.table_name, "TALEBOARD_BUCKET": bucket.bucket_name}

        # Lambdas
        worker = lambda_.DockerImageFunction(
            self, "Worker",
            code=lambda_.DockerImageCode.from_image_asset(
                str(REPO_ROOT), file="docker/worker.Dockerfile", platform=ecr_assets.Platform.LINUX_AMD64
            ),
            architecture=lambda_.Architecture.X86_64,
            memory_size=3008,
            timeout=Duration.minutes(15),
            environment={
                **storage_env,
                "TALEBOARD_QUEUE_URL": jobs.queue_url,
                "TOGETHER_API_KEY_PARAMETER": together_key.parameter_name,
            },
            log_group=self._log_group("Worker"),
        )
        api_fn = PythonFunction(
            self, "ApiFunction",
            entry=str(SRC_DIR),
            index="taleboard/api/app.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_13,
            memory_size=512,
            timeout=Duration.seconds(15),
            environment={**storage_env, "TALEBOARD_QUEUE_URL": jobs.queue_url, "TALEBOARD_API_KEY_PARAMETER":api_key.parameter_name},
            bundling=BundlingOptions(asset_excludes=["__pycache__", "*.egg-info"]),
            log_group=self._log_group("Api"),
        )
        dead_letter_fn = PythonFunction(
            self, "DeadLetterFunction",
            entry=str(SRC_DIR),
            index="taleboard/jobs/dead_letters.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_13,
            timeout=Duration.seconds(30),
            environment=storage_env,
            bundling=BundlingOptions(asset_excludes=["__pycache__", "*.egg-info"]),
            log_group=self._log_group("DeadLetter"),
        )

        # max_concurrency caps parallel renders (2 is the minimum SQS allows) -- a cost guard, not a throughput setting
        worker.add_event_source(event_sources.SqsEventSource(jobs, batch_size=1, max_concurrency=2))
        dead_letter_fn.add_event_source(event_sources.SqsEventSource(dead_letters, batch_size=1))

        # Permissions (consuming a queue already grants sqs:ChangeMessageVisibility; the SecureStrings use the AWS-managed aws/ssm key, so no explicit kms:Decrypt is needed)
        for fn in (api_fn, worker, dead_letter_fn):
            table.grant_read_write_data(fn)
        for fn in (api_fn, worker):
            bucket.grant_read_write(fn, "projects/*")
            jobs.grant_send_messages(fn)  # API enqueues; worker self-continues
        together_key.grant_read(worker)
        api_key.grant_read(api_fn) # Only the API checks the key -- the worker never sees it
        worker.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[
                f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{HAIKU_PROFILE_ID}",
                f"arn:aws:bedrock:*::foundation-model/{HAIKU_MODEL_ID}",  # The EU profile routes across EU Regions
            ],
        ))

        # HTTP API -- an explicit GET/POST route rather than $default: a catch-all route also catches OPTIONS, which stops
        # API Gateway answering CORS preflights itself 
        # Add any new method (eg:- the editor's PUT/DELETE) to this list
        # Throttled because POST /story spends real money
        http_api = apigw.HttpApi(
            self, "HttpApi",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=cors_origins,
                allow_methods=[apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.POST],
                allow_headers=["content-type", "x-api-key"],
                max_age=Duration.hours(1),
            ),
            create_default_stage=False,
        )
        http_api.add_routes(
            path="/{proxy+}",
            methods=[apigw.HttpMethod.GET, apigw.HttpMethod.POST],
            integration=HttpLambdaIntegration("ApiIntegration", api_fn),
        )

        stage = http_api.add_stage(
            "DefaultStage",
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(rate_limit=5, burst_limit=10),
        )

        # Alarm -- the dead-letter Lambda drains the DLQ at once, so alarm on messages received, not messages visible
        alarm = cloudwatch.Alarm(
            self, "DeadLetterAlarm",
            metric=dead_letters.metric_number_of_messages_received(period=Duration.minutes(5), statistic="Sum"),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="A render job exhausted its retries and was dead-lettered.",
        )
        if alarm_email:
            topic = sns.Topic(self, "Alerts")
            topic.add_subscription(subscriptions.EmailSubscription(alarm_email))
            alarm.add_alarm_action(cw_actions.SnsAction(topic))

        CfnOutput(self, "ApiUrl", value=stage.url)
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "BucketName", value=bucket.bucket_name)

    def _log_group(self, name: str) -> logs.LogGroup:
        """
        Builds a log group with two-week retention, so logs don't pile up (and cost) forever.

        Arguments:
            name: str - Prefix for the construct ID.

        Returns:
            logs.LogGroup - The log group.
        """
        return logs.LogGroup(
            self, f"{name}Logs", retention=logs.RetentionDays.TWO_WEEKS, removal_policy=RemovalPolicy.DESTROY
        )