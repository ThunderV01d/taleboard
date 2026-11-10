"""
The guest sign-in: POST /auth/guest, the one route with no authorizer, hands out tokens for the shared guest user.

Every visitor who clicks "Browse as guest" is signed in as the same Cognito user, guest@taleboard.invalid, through the
guest app client. Its password lives only in Secrets Manager (generated at deploy time), and the browser only ever gets
short-lived tokens -- never the password, and never a refresh token: it asks here again when the token runs out.

The user is created here the first time it's needed (and its password reset if the secret has changed), so a new
stack needs no hand-made setup. A ".invalid" address can never receive mail, so nobody can reset its password either.
What the guest may do is decided by the API (taleboard.api.deps.refuse_guest_writes): it can read the projects shared
with it, and nothing else.

Runs as its own small Lambda, packaged with only this folder -- it needs nothing but boto3.

Attributes:
    GUEST_USERNAME: str - The guest user's username (an email, as the pool signs in by email).
    GUEST_GROUP: str - The Cognito group the guest user is in.
"""
import json
import os
from functools import lru_cache

import boto3

GUEST_USERNAME = "guest@taleboard.invalid"
GUEST_GROUP = "guests"


@lru_cache
def _cognito():
    return boto3.client("cognito-idp")


@lru_cache
def _password() -> str:
    """
    The guest user's password, read from Secrets Manager once per container.
    """
    return boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["TALEBOARD_GUEST_SECRET"])["SecretString"]


def _ensure_guest(pool_id: str) -> None:
    """
    Creates the guest user, in the guests group and with the secret's password -- or, if it already exists, sets its password to the secret's (a secret rotated or recreated since).
    """
    cognito = _cognito()
    try:
        cognito.admin_create_user(
            UserPoolId=pool_id,
            Username=GUEST_USERNAME,
            UserAttributes=[{"Name": "email", "Value": GUEST_USERNAME}, {"Name": "email_verified", "Value": "true"}],
            MessageAction="SUPPRESS",  # No welcome email (there's nowhere to send it)
        )
    except cognito.exceptions.UsernameExistsException:
        pass  # Made by another visitor's first call a moment ago, or here before with an older password
    cognito.admin_set_user_password(UserPoolId=pool_id, Username=GUEST_USERNAME, Password=_password(), Permanent=True)
    cognito.admin_add_user_to_group(UserPoolId=pool_id, Username=GUEST_USERNAME, GroupName=GUEST_GROUP)


def guest_tokens(pool_id: str, client_id: str) -> dict:
    """
    Signs in as the guest user -- creating it first if this is the first time -- and returns the tokens to hand the browser.

    Arguments:
        pool_id: str - The user pool.
        client_id: str - The guest app client (it allows only this admin sign-in, and issues short-lived tokens).

    Returns:
        dict - access_token, id_token, expires_in (seconds) and token_type. No refresh token, on purpose.
    """
    cognito = _cognito()
    sign_in = lambda: cognito.admin_initiate_auth(
        UserPoolId=pool_id,
        ClientId=client_id,
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": GUEST_USERNAME, "PASSWORD": _password()},
    )
    try:
        result = sign_in()
    except (cognito.exceptions.UserNotFoundException, cognito.exceptions.NotAuthorizedException):
        _ensure_guest(pool_id)  # Not made yet, or its password no longer matches the secret
        result = sign_in()
    tokens = result["AuthenticationResult"]
    return {
        "access_token": tokens["AccessToken"],
        "id_token": tokens["IdToken"],
        "expires_in": tokens["ExpiresIn"],
        "token_type": tokens["TokenType"],
    }


def handler(event: dict, context) -> dict:
    """
    POST /auth/guest entry point (API Gateway HTTP API, payload v2.0).

    Arguments:
        event: dict - The API Gateway event (nothing in it is used).
        context: LambdaContext - Unused.

    Returns:
        dict - 200 with the guest's tokens, or 503 if they couldn't be issued.
    """
    headers = {"content-type": "application/json", "cache-control": "no-store"}  # Tokens must never be cached on the way
    try:
        body = guest_tokens(os.environ["TALEBOARD_USER_POOL_ID"], os.environ["TALEBOARD_GUEST_CLIENT_ID"])
    except Exception as error:  # Logged; the visitor just sees that guest browsing is unavailable
        print(f"Guest sign-in failed: {type(error).__name__}: {error}")
        return {"statusCode": 503, "headers": headers, "body": json.dumps({"detail": "Guest browsing isn't available right now -- please try again later"})}
    return {"statusCode": 200, "headers": headers, "body": json.dumps(body)}
