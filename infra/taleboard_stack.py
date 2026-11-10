"""
CDK stack for the TaleBoard backend: storage, the job queue, and the API, worker and dead-letter Lambdas.

Attributes:
    REPO_ROOT: Path - Repository root, the worker image's build context.
    SRC_DIR: Path - Source folder bundled into the API and dead-letter Lambdas (with src/requirements.txt).
    PROJECTS_INDEX: str - Name of the sparse project-listing GSI (must match taleboard.storage.storyboard_store).
    TOGETHER_KEY_PARAMETER: str - Name of the SSM SecureString holding the Together AI API key (created by hand).
    MAX_ATTEMPTS: int - Deliveries before a job is dead-lettered (must match taleboard.jobs.generation_worker.MAX_ATTEMPTS).
    HAIKU_PROFILE_ID: str - Bedrock EU cross-region inference profile used by the story breakdown.
    HAIKU_MODEL_ID: str - Foundation model behind that profile.
    GOOGLE_CLIENT_ID: str - Google OAuth client ID (not a secret -- it appears in every Google sign-in URL).
    GOOGLE_SECRET_NAME: str - Name of the Secrets Manager secret holding the Google client secret (created by hand).
    GUEST_GROUP: str - The Cognito group the shared guest user is in (must match taleboard.auth.guest_session.GUEST_GROUP).
    GUEST_THROTTLE: dict - Rate (requests a second) and burst limits of POST /auth/guest, for all callers together.
"""
from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, SecretValue, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_cognito as cognito
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
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk.aws_apigatewayv2_authorizers import HttpUserPoolAuthorizer
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from aws_cdk.aws_lambda_python_alpha import BundlingOptions, PythonFunction
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
PROJECTS_INDEX = "projects-by-created-at"
TOGETHER_KEY_PARAMETER = "/taleboard/together-api-key"
MAX_ATTEMPTS = 5
HAIKU_PROFILE_ID = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
HAIKU_MODEL_ID = "anthropic.claude-haiku-4-5-20251001-v1:0"
GOOGLE_CLIENT_ID = "862089955034-l63lk5q2j8m1jp23m65o2v8f3oeejdah.apps.googleusercontent.com"
GOOGLE_SECRET_NAME = "taleboard/google-client-secret"
GUEST_GROUP = "guests"
GUEST_THROTTLE = {"ThrottlingRateLimit": 1, "ThrottlingBurstLimit": 5}

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
            cors=[s3.CorsRule(
                allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.POST],  # POST for browser uploads; GET so the canvas can draw (and export) images
                allowed_origins=cors_origins,
                allowed_headers=["*"],
                max_age=3600,
            )],
        )

        # Generation job queue -- FIFO, grouped by project, so a project's jobs run one at a time and in order
        generation_dead_letters = sqs.Queue(self, "GenerationDeadLetters", fifo=True, retention_period=Duration.days(14), enforce_ssl=True)
        generation_jobs = sqs.Queue(
            self, "GenerationJobs",
            fifo=True,
            visibility_timeout=Duration.minutes(16),
            dead_letter_queue=sqs.DeadLetterQueue(queue=generation_dead_letters, max_receive_count=MAX_ATTEMPTS),
            enforce_ssl=True,
        )

        together_key = ssm.StringParameter.from_secure_string_parameter_attributes(
            self, "TogetherKey", parameter_name=TOGETHER_KEY_PARAMETER
        )

        storage_env = {"TALEBOARD_TABLE": table.table_name, "TALEBOARD_BUCKET": bucket.bucket_name}

        # Users -- email + password with an emailed confirmation code (Google sign-in is added on top later)
        user_pool = cognito.UserPool(
            self, "Users",
            feature_plan=cognito.FeaturePlan.LITE,
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            sign_in_case_sensitive=False,
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            user_verification=cognito.UserVerificationConfig(
                email_style=cognito.VerificationEmailStyle.CODE,
                email_subject="Your TaleBoard confirmation code",
                email_body="Your TaleBoard confirmation code is {####}"
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=10,
                require_lowercase= False,
                require_uppercase=False,
                require_digits=False,
                require_symbols=False
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY
        ) # Kept if the stack is deleted (the default for user pools), so accounts can never wiped by accident

        # Google sign-in -- the secret is read from Secrets Manager at deploy time, so it never appears in the template
        google = cognito.UserPoolIdentityProviderGoogle(
            self, "Google",
            user_pool=user_pool,
            client_id=GOOGLE_CLIENT_ID,
            client_secret_value=SecretValue.secrets_manager(GOOGLE_SECRET_NAME),
            scopes=["openid","email","profile"],
            attribute_mapping=cognito.AttributeMapping(
                email=cognito.ProviderAttribute.GOOGLE_EMAIL,
                email_verified=cognito.ProviderAttribute.GOOGLE_EMAIL_VERIFIED # The linking trigger only trusts verified emails
            )
        )

        # Links a first Google sign-in to an existing password account with the same email
        link_accounts = lambda_.Function(
            self, "LinkAccoutnsFunction",
            code=lambda_.Code.from_asset(str(SRC_DIR / "taleboard" / "auth"), exclude=["__pycache__"]),
            handler="link_accounts.handler",
            runtime=lambda_.Runtime.PYTHON_3_13,
            timeout=Duration.seconds(5), # Cognito waits at most 5 seconds for a trigger
            log_group=self._log_group("LinkAccounts")
        )

        # Any pool in this account and region, not user_pool.user_pool_arn -- that would be a circular dependency (as the pool needs the function as its trigger)
        link_accounts.add_to_role_policy(iam.PolicyStatement(
            actions=["cognito-idp:ListUsers", "cognito-idp:AdminLinkProviderForUser"],
            resources=[f"arn:aws:cognito-idp:{self.region}:{self.account}:userpool/*"]
        ))

        user_pool.add_trigger(cognito.UserPoolOperation.PRE_SIGN_UP, link_accounts)        

        web_client = user_pool.add_client(
            "WebClient",
            generate_secret=False, # A browser can't keep a secret
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True), # Code flow only -- never implicit
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
                callback_urls=[f"{origin}/auth/callback" for origin in cors_origins],
                logout_urls=[f"{origin}/" for origin in cors_origins],
            ),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO, cognito.UserPoolClientIdentityProvider.GOOGLE],
            auth_flows=cognito.AuthFlow(user_srp=True,user_password=True), # SRP for the browser; plain password for CLI-testing
            prevent_user_existence_errors=True,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30)
        )
        web_client.node.add_dependency(google) # The client names Google as a provider, so Google must exist first

        # Cognito's own domain -- Google redirects back to it after sign-in. Named after the stack (and account), so the dev and live stacks never clash
        auth_domain = user_pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=f"{self.stack_name.lower()}-{self.account}"),
        )

                # The shared guest user -- made by the guest sign-in Lambda on first use (taleboard.auth.guest_session), in this
        # group, with this password. The password only ever lives in Secrets Manager; the browser gets short-lived tokens
        cognito.CfnUserPoolGroup(
            self, "GuestGroup",
            user_pool_id=user_pool.user_pool_id,
            group_name=GUEST_GROUP,
            description="The shared guest user -- the API lets it read the projects shared with it, and change nothing",
        )
        guest_password = secretsmanager.Secret(
            self, "GuestPassword",
            description="Password of the shared TaleBoard guest user (only the guest sign-in Lambda reads it)",
            generate_secret_string=secretsmanager.SecretStringGenerator(password_length=40, exclude_punctuation=True, require_each_included_type=True),
        )
        # Its own app client, so its tokens can be short-lived -- the guest page asks for new ones rather than refreshing
        guest_client = user_pool.add_client(
            "GuestClient",
            generate_secret=False,
            disable_o_auth=True,
            auth_flows=cognito.AuthFlow(admin_user_password=True),  # Only the Lambda's admin sign-in -- never a browser's
            prevent_user_existence_errors=True,
            access_token_validity=Duration.minutes(15),
            id_token_validity=Duration.minutes(15),
            refresh_token_validity=Duration.minutes(60),  # The least Cognito allows; never handed to the browser
        )

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
                "TALEBOARD_GENERATION_QUEUE_URL": generation_jobs.queue_url,
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
            environment={
                **storage_env,
                "TALEBOARD_GENERATION_QUEUE_URL": generation_jobs.queue_url,
                "TALEBOARD_GUEST_CLIENT_ID": guest_client.user_pool_client_id,  # A token from it is the guest's, read-only
            },
            bundling=BundlingOptions(asset_excludes=["__pycache__", "*.egg-info"]),
            log_group=self._log_group("Api"),
        )
        guest_session_fn = lambda_.Function(
            self, "GuestSessionFunction",
            code=lambda_.Code.from_asset(str(SRC_DIR / "taleboard" / "auth"), exclude=["__pycache__"]),
            handler="guest_session.handler",
            runtime=lambda_.Runtime.PYTHON_3_13,
            timeout=Duration.seconds(10),
            environment={
                "TALEBOARD_USER_POOL_ID": user_pool.user_pool_id,
                "TALEBOARD_GUEST_CLIENT_ID": guest_client.user_pool_client_id,
                "TALEBOARD_GUEST_SECRET": guest_password.secret_arn,
            },
            log_group=self._log_group("GuestSession"),
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
        worker.add_event_source(event_sources.SqsEventSource(generation_jobs, batch_size=1, max_concurrency=2))
        dead_letter_fn.add_event_source(event_sources.SqsEventSource(generation_dead_letters, batch_size=1))

        # Permissions (consuming a queue already grants sqs:ChangeMessageVisibility; the SecureStrings use the AWS-managed aws/ssm key, so no explicit kms:Decrypt is needed)
        for fn in (api_fn, worker, dead_letter_fn):
            table.grant_read_write_data(fn)
        for fn in (api_fn, worker):
            bucket.grant_read_write(fn, "projects/*")
            generation_jobs.grant_send_messages(fn) # API enqueues; worker self-continues
        together_key.grant_read(worker)
        guest_password.grant_read(guest_session_fn)
        guest_session_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["cognito-idp:AdminInitiateAuth", "cognito-idp:AdminCreateUser", "cognito-idp:AdminSetUserPassword", "cognito-idp:AdminAddUserToGroup"],
            resources=[user_pool.user_pool_arn],
        ))
        worker.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[
                f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{HAIKU_PROFILE_ID}",
                f"arn:aws:bedrock:*::foundation-model/{HAIKU_MODEL_ID}",  # The EU profile routes across EU Regions
            ],
        ))

        # HTTP API -- an explicit GET/POST route rather than $default: a catch-all route also catches OPTIONS, which stops
        # API Gateway answering CORS preflights itself 
        # Every method the API uses must be listed here and in allow_methods
        # Throttled because POST /story spends real money
        http_api = apigw.HttpApi(
            self, "HttpApi",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=cors_origins,
                allow_methods=[apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.POST, apigw.CorsHttpMethod.PUT, apigw.CorsHttpMethod.PATCH, apigw.CorsHttpMethod.DELETE],
                allow_headers=["content-type", "authorization"],
                max_age=Duration.hours(1),
            ),
            create_default_stage=False,
        )
        http_api.add_routes(
            path="/{proxy+}",
            methods=[apigw.HttpMethod.GET, apigw.HttpMethod.POST, apigw.HttpMethod.PUT, apigw.HttpMethod.PATCH, apigw.HttpMethod.DELETE],
            integration=HttpLambdaIntegration("ApiIntegration", api_fn),
            authorizer=HttpUserPoolAuthorizer("UserAuthorizer", user_pool, user_pool_clients=[web_client, guest_client]),
        )
        # The one route without the authorizer: it's how a visitor gets the guest's tokens in the first place
        guest_routes = http_api.add_routes(
            path="/auth/guest",
            methods=[apigw.HttpMethod.POST],
            integration=HttpLambdaIntegration("GuestSessionIntegration", guest_session_fn),
        )

        stage = http_api.add_stage(
            "DefaultStage",
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(rate_limit=5, burst_limit=10),
        )

        # The guest sign-in gets a tighter limit of its own (HTTP APIs can't limit per IP -- that would need WAF). A
        # browser only calls it every 15 minutes, as its token runs out
        stage.node.default_child.add_property_override("RouteSettings", {"POST /auth/guest": GUEST_THROTTLE})
        for route in guest_routes:
            stage.node.add_dependency(route)  # The route must exist before the stage can name it

        # Alarm -- the dead-letter Lambda drains the DLQ at once, so alarm on messages received, not messages visible
        generation_alarm = cloudwatch.Alarm(
            self, "GenerationDeadLetterAlarm",
            metric=generation_dead_letters.metric_number_of_messages_received(period=Duration.minutes(5), statistic="Sum"),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="A genneration job exhausted its retries and was dead-lettered."
        )
        if alarm_email:
            topic = sns.Topic(self, "Alerts")
            topic.add_subscription(subscriptions.EmailSubscription(alarm_email))
            generation_alarm.add_alarm_action(cw_actions.SnsAction(topic))

        CfnOutput(self, "ApiUrl", value=stage.url)
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=web_client.user_pool_client_id)
        CfnOutput(self, "AuthDomain", value=auth_domain.base_url())

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