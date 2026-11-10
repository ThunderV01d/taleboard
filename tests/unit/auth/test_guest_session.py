"""
Unit tests for guest_session, the POST /auth/guest Lambda that hands out the shared guest user's tokens.

Uses moto's fakes of Cognito and Secrets Manager, which issue real (signed) JWTs -- so the token's own claims are fed
to the API to check what the guest can reach.

Covers creating the guest user on first use (in the guests group), signing in again, recovering from a changed
password, and never handing out a refresh token. (That its token reads a shared project but not an unshared one is in
tests/unit/api/test_permissions.py.)
"""
import base64
import json

import pytest

from taleboard.auth import guest_session


def claims_of(token: str) -> dict:
    """
    A JWT's claims (its payload), unverified -- API Gateway's authorizer does the verifying.
    """
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_the_first_call_creates_the_guest_user_and_signs_it_in(guest_pool):
    """
    Verifies that the guest user is made on first use -- confirmed, in the guests group -- and that the tokens belong to it.
    """
    response = guest_session.handler({}, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    user = guest_pool["idp"].admin_get_user(UserPoolId=guest_pool["pool"], Username=guest_session.GUEST_USERNAME)
    groups = guest_pool["idp"].admin_list_groups_for_user(UserPoolId=guest_pool["pool"], Username=guest_session.GUEST_USERNAME)["Groups"]
    assert user["UserStatus"] == "CONFIRMED"
    assert [g["GroupName"] for g in groups] == [guest_session.GUEST_GROUP]
    assert claims_of(body["access_token"])["sub"] == next(a["Value"] for a in user["UserAttributes"] if a["Name"] == "sub")


def test_the_browser_never_gets_a_refresh_token_and_nothing_is_cached(guest_pool):
    """
    Verifies the response: an access and ID token with their lifetime, no refresh token, and no-store.
    """
    response = guest_session.handler({}, None)

    assert set(json.loads(response["body"])) == {"access_token", "id_token", "expires_in", "token_type"}
    assert response["headers"]["cache-control"] == "no-store"


def test_every_visitor_signs_in_as_the_same_guest(guest_pool):
    """
    Verifies that later calls sign in as the existing guest rather than making another.
    """
    first = json.loads(guest_session.handler({}, None)["body"])
    second = json.loads(guest_session.handler({}, None)["body"])

    assert claims_of(first["access_token"])["sub"] == claims_of(second["access_token"])["sub"]
    assert len(guest_pool["idp"].list_users(UserPoolId=guest_pool["pool"])["Users"]) == 1


def test_a_changed_password_is_set_again_from_the_secret(guest_pool):
    """
    Verifies that if the guest's password no longer matches the secret (a recreated secret, say), it's set from the secret and the sign-in goes ahead.
    """
    guest_session.handler({}, None)
    guest_pool["idp"].admin_set_user_password(UserPoolId=guest_pool["pool"], Username=guest_session.GUEST_USERNAME, Password="Someone-changed-it-2", Permanent=True)

    assert guest_session.handler({}, None)["statusCode"] == 200


def test_a_failure_is_a_503_without_details(guest_pool, monkeypatch):
    """
    Verifies that if the tokens can't be issued, the visitor gets a plain 503 (the reason only goes to the logs).
    """
    monkeypatch.setenv("TALEBOARD_GUEST_CLIENT_ID", "no-such-client")

    response = guest_session.handler({}, None)

    assert response["statusCode"] == 503
    assert "no-such-client" not in response["body"]
