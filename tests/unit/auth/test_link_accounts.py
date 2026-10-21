"""
Unit tests for link_accounts, the Cognito pre-sign-up trigger.

Uses a fake Cognito client, which records the filters it's asked for and the links it's asked to make.

Covers linking a first Google sign-in to a confirmed email/password account, the cases where it mustn't link, and refusing a password sign-up for an email that already signs in with Google.
"""
import pytest

from taleboard.auth import link_accounts

POOL = "eu-west-2_pool"


class FakeCognito:
    """
    Stands in for the Cognito client.

    Attributes:
        users: list[dict] - Users ListUsers returns (whatever the filter).
        filters: list[str] - Filters ListUsers was called with.
        links: list[dict] - Arguments of every AdminLinkProviderForUser call.
    """
    def __init__(self, users: list[dict]):
        self.users = users
        self.filters = []
        self.links = []

    def list_users(self, UserPoolId: str, Filter: str) -> dict:
        """Records the filter, and returns every user."""
        assert UserPoolId == POOL
        self.filters.append(Filter)
        return {"Users": self.users}

    def admin_link_provider_for_user(self, **kwargs) -> None:
        """Records the link."""
        self.links.append(kwargs)


@pytest.fixture
def cognito(monkeypatch):
    """
    Installs a fake Cognito client with no users; tests add the users they need.

    Arguments:
        monkeypatch: pytest.MonkeyPatch - Used to swap the client in.

    Returns:
        FakeCognito - The fake.
    """
    fake = FakeCognito([])
    monkeypatch.setattr(link_accounts, "_cognito", lambda: fake)
    return fake


def _event(source: str, email: str | None = "mara@example.com", verified: str = "true", user_name: str = "google_10769150350006150715") -> dict:
    """
    Builds a pre-sign-up event.

    Arguments:
        source: str - The trigger source.
        email: str - The email being signed up. Defaults to mara@example.com (None leaves it out).
        verified: str - Whether the provider verified the email ("true"/"false"). Defaults to "true".
        user_name: str - The new user's name. Defaults to a Google one.

    Returns:
        dict - The event.
    """
    attributes = {"email_verified": verified} | ({"email": email} if email else {})
    return {"triggerSource": source, "userPoolId": POOL, "userName": user_name, "request": {"userAttributes": attributes}, "response": {}}


def _user(status: str, username: str = "3f1c-mara") -> dict:
    """
    Builds a user as ListUsers returns it.

    Arguments:
        status: str - Its UserStatus.
        username: str - Its Username. Defaults to a native user's.

    Returns:
        dict - The user.
    """
    return {"Username": username, "UserStatus": status}


def test_a_first_google_sign_in_is_linked_to_the_confirmed_password_account(cognito):
    """
    Verifies that Google is linked to the existing account (as the destination), by Google's own user ID, and that sign-up goes ahead.
    """
    cognito.users = [_user("CONFIRMED")]
    event = _event("PreSignUp_ExternalProvider")

    assert link_accounts.handler(event, None) is event
    assert cognito.links == [{
        "UserPoolId": POOL,
        "DestinationUser": {"ProviderName": "Cognito", "ProviderAttributeValue": "3f1c-mara"},
        "SourceUser": {"ProviderName": "Google", "ProviderAttributeName": "Cognito_Subject", "ProviderAttributeValue": "10769150350006150715"},
    }]
    assert cognito.filters == ['email = "mara@example.com"']


def test_the_provider_name_is_always_google_whatever_the_user_names_case(cognito):
    """
    Verifies that a "Google_" prefix (rather than "google_") links the same way -- the provider name never comes from the user name.
    """
    cognito.users = [_user("CONFIRMED")]

    link_accounts.handler(_event("PreSignUp_ExternalProvider", user_name="Google_42"), None)

    assert cognito.links[0]["SourceUser"]["ProviderName"] == "Google"
    assert cognito.links[0]["SourceUser"]["ProviderAttributeValue"] == "42"


def test_an_email_google_hasnt_verified_is_never_linked(cognito):
    """
    Verifies that an unverified Google email can't take over a password account.
    """
    cognito.users = [_user("CONFIRMED")]

    link_accounts.handler(_event("PreSignUp_ExternalProvider", verified="false"), None)

    assert cognito.links == []


@pytest.mark.parametrize("users", [[], [_user("UNCONFIRMED")], [_user("EXTERNAL_PROVIDER", "google_1")], [_user("FORCE_CHANGE_PASSWORD")]])
def test_google_isnt_linked_without_a_confirmed_password_account(cognito, users):
    """
    Verifies that nothing is linked when there's no account, or only one that never proved it owns the email.

    Arguments:
        users: list[dict] - The users with the same email.
    """
    cognito.users = users

    assert link_accounts.handler(_event("PreSignUp_ExternalProvider"), None)["triggerSource"] == "PreSignUp_ExternalProvider"
    assert cognito.links == []


def test_a_password_sign_up_for_an_email_that_uses_google_is_refused(cognito):
    """
    Verifies that someone can't create a second, password account for an email that already signs in with Google.
    """
    cognito.users = [_user("EXTERNAL_PROVIDER", "google_1")]

    with pytest.raises(Exception, match="already signs in with Google"):
        link_accounts.handler(_event("PreSignUp_SignUp", user_name="mara@example.com"), None)


def test_an_ordinary_password_sign_up_goes_ahead(cognito):
    """
    Verifies that a password sign-up for a new email is let through, with no links made.
    """
    event = _event("PreSignUp_SignUp", user_name="mara@example.com")

    assert link_accounts.handler(event, None) is event
    assert cognito.links == []


@pytest.mark.parametrize("event", [_event("PreSignUp_AdminCreateUser"), _event("PreSignUp_ExternalProvider", email=None)])
def test_other_sign_ups_pass_through_untouched(cognito, event):
    """
    Verifies that admin-created users, and sign-ups without an email, aren't looked up or changed.

    Arguments:
        event: dict - A pre-sign-up event to ignore.
    """
    assert link_accounts.handler(event, None) is event
    assert (cognito.filters, cognito.links) == ([], [])


def test_quotes_in_an_email_cant_break_out_of_the_filter(cognito):
    """
    Verifies that quotes and backslashes in an email are escaped in the ListUsers filter.
    """
    link_accounts.handler(_event("PreSignUp_SignUp", email='a"b\\c@example.com'), None)

    assert cognito.filters == ['email = "a\\"b\\\\c@example.com"']
