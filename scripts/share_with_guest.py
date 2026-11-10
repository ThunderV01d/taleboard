"""
Shares one of your projects with the guest user (to view), stops sharing it, or lists who it's shared with -- so
visitors who click "Browse as guest" can open it.

It signs in as you (the project's owner) and calls the API like the app does, so it needs no AWS credentials -- only
your TaleBoard email and password, and the stack's outputs (ApiUrl and UserPoolClientId). The guest's user ID is found
by signing in as the guest through POST /auth/guest, which also creates the guest user if this is the first time.

Usage (from the repository root, with the backend's Python environment):

    python scripts/share_with_guest.py share  PROJECT_ID --api API_URL --client-id CLIENT_ID --email YOU@EXAMPLE.COM
    python scripts/share_with_guest.py revoke PROJECT_ID --api API_URL --client-id CLIENT_ID --email YOU@EXAMPLE.COM
    python scripts/share_with_guest.py list   PROJECT_ID --api API_URL --client-id CLIENT_ID --email YOU@EXAMPLE.COM

Your password is asked for (or read from TALEBOARD_PASSWORD). A project's ID is the last part of its editor address
(/projects/PROJECT_ID).
"""
import argparse
import base64
import getpass
import json
import os
import urllib.error
import urllib.request

import boto3
from botocore import UNSIGNED
from botocore.config import Config


def _call(method: str, url: str, token: str | None = None, body: dict | None = None) -> dict | list | None:
    """
    Calls the API, returning its JSON answer (None for an empty one) -- or exiting with its error.
    """
    request = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None)
    request.add_header("content-type", "application/json")
    if token:
        request.add_header("authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request) as response:
            text = response.read().decode()
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{method} {url} failed ({error.code}): {error.read().decode()}") from None
    return json.loads(text) if text else None


def _sign_in(region: str, client_id: str, email: str, password: str) -> str:
    """
    Signs in as the project's owner, returning an access token. (Cognito's sign-in needs no AWS credentials.)
    """
    cognito = boto3.client("cognito-idp", region_name=region, config=Config(signature_version=UNSIGNED))
    result = cognito.initiate_auth(ClientId=client_id, AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": email, "PASSWORD": password})
    return result["AuthenticationResult"]["AccessToken"]


def _guest_user_id(api: str) -> str:
    """
    The guest user's ID: the sub claim of a token from POST /auth/guest.
    """
    token = _call("POST", f"{api}/auth/guest")["access_token"]
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["sub"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Share a project with the TaleBoard guest user (to view), stop sharing it, or list its shares.")
    parser.add_argument("action", choices=["share", "revoke", "list"])
    parser.add_argument("project_id")
    parser.add_argument("--api", required=True, help="The stack's ApiUrl output")
    parser.add_argument("--client-id", required=True, help="The stack's UserPoolClientId output")
    parser.add_argument("--email", required=True, help="Your TaleBoard email (the project's owner)")
    parser.add_argument("--region", default="eu-west-2")
    args = parser.parse_args()

    api = args.api.rstrip("/")
    password = os.environ.get("TALEBOARD_PASSWORD") or getpass.getpass("Your TaleBoard password: ")
    token = _sign_in(args.region, args.client_id, args.email, password)
    shares = f"{api}/projects/{args.project_id}/shares"

    if args.action == "list":
        for share in _call("GET", shares, token):
            print(f"{share['grantee_id']}  {share['role']}  (since {share['created_at']})")
        return
    guest = _guest_user_id(api)
    if args.action == "share":
        _call("PUT", f"{shares}/{guest}", token, {"role": "viewer"})
        print(f"Shared {args.project_id} with the guest ({guest}) to view.")
    else:
        _call("DELETE", f"{shares}/{guest}", token)
        print(f"Stopped sharing {args.project_id} with the guest.")


if __name__ == "__main__":
    main()
