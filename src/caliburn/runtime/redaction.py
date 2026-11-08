"""Known platform-secret guard; decoded data cannot hide values with JSON escapes."""

import json

from sqlalchemy.engine import make_url


def platform_secrets(settings):
    return tuple(
        value
        for value in (
            settings.api_token,
            settings.upstream_api_key,
            make_url(settings.database_url).password,
        )
        if value
    )


def contains_secret(value, secrets, _depth=0):
    if _depth > 30:
        return True
    if isinstance(value, str):
        if any(secret and secret in value for secret in secrets):
            return True
        if value[:1] in {"{", "[", '"'} and len(value) <= 131072:
            try:
                decoded = json.loads(value)
            except (ValueError, RecursionError):
                return False
            if decoded != value:
                return contains_secret(decoded, secrets, _depth + 1)
        return False
    if isinstance(value, dict):
        return any(
            contains_secret(key, secrets, _depth + 1) or contains_secret(item, secrets, _depth + 1)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_secret(item, secrets, _depth + 1) for item in value)
    return False
