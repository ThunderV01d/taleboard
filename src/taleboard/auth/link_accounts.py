"""
Cognito pre-sign-up trigger that keeps one account per email address across the two ways of signing in.

A first Google sign-in, with an email that already has a confirmed email/password account is linked to that account -- the user keeps the same user ID and projects.

An email/password sign-up, with an email that already signs in with Google, is refused.

Self-contained (boto3 only, which Lambda provides), so the function is deployed from this package alone.

Attributes:
    GOOGLE: str - Cognito's name for the Google identity provider.
"""
from functools import lru_cache
import boto3

GOOGLE = "Google"

@lru_cache
def _cognito():
    """
    Creates the Cognito client once per container.

    Returns:
        CognitoIdentityProvider.Client - The client.
    """
    return boto3.client("cognito-idp")

def _users_with_email(pool_id: str, email: str) -> list[dict]:
    """
    Finds the users in the pool with this email address.

    Arguments:
        pool_id: str - The user's pool ID.
        email: str - The email address.

    Returns:
        list[dict] - The users (as returned by ListUsers).
    """
    escaped = email.replace("\\","\\\\").replace('"','\\"') # The filter is a quoted string -- an email can't break out of it
    return _cognito().list_users(UserPoolId=pool_id, Filter=f'email = "{escaped}"')["Users"]

def _link_to_password_account(event: dict, users: list[dict]) -> None:
    """
    Links a first Google sign-in to the confirmed email/password account with the same email (if there is one).

    Only happens when Google says it has verified the email -- otherwise anyone could take over an account by adding its address to a Google account.

    Arguments:
        event: dict - The pre-sign-up event.
        users: list[dict] - The users with the same email.
    """
    if event["request"]["userAttributes"].get("email_verified") != "true":
        return
    confirmed = [u for u in users if u["UserStatus"] == "CONFIRMED"] # Confirmed implies that the user has proven that they own the email with a verification code

    if not confirmed:
        return

    google_user_id = event["userName"].split("_",1)[1] # "google_{id}" -- the prefix's case isn't reliable, so the provider name comes from GOOGLE

    _cognito().admin_link_provider_for_user(
        UserPoolId=event["userPoolId"],
        DestinationUser={"ProviderName": "Cognito", "ProviderAttributeValue": confirmed[0]["Username"]},
        SourceUser={"ProviderName": GOOGLE, "ProviderAttributeName": "Cognito_Subject", "ProviderAttributeValue": google_user_id}
    )


def handler (event: dict, context) -> dict:
    """
    Pre-sign-up trigger entry point.
    
    Returning the event lets the sign-up go ahead; raising it refuses it, with the message shown to the user.

    Arguments:
        event: dict - The pre-sign-up event.
        context: LambdaContext - Unused.

    Returns:
        dict - The event, unchanged.
    """
    email = event["request"]["userAttributes"].get("email")
    if not email:
        return event
    
    if event["triggerSource"] == "PreSignUp_ExternalProvider":
        _link_to_password_account(event,_users_with_email(event["userPoolId"], email))
    elif event["triggerSource"] == "PreSignUp_SignUp":
        if any(u["UserStatus"] == "EXTERNAL_PROVIDER" for u in _users_with_email(event["userPoolId"], email)):
            raise Exception("This email already signs in with Google -- use Sign in with Google instead")
    return event