"""Small health metadata model for configured web search providers."""

from __future__ import annotations

from urllib.parse import urlparse

from allCode.core.models import CoreModel


class WebHealth(CoreModel):
    configured: bool = False
    backend: str = "disabled"
    search_url_host: str = ""
    supports_json: bool = False
    last_error_type: str = ""
    offline: bool = False


def health_payload(value: object) -> dict[str, object]:
    if isinstance(value, WebHealth):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        try:
            return WebHealth.model_validate(value).model_dump(mode="json")
        except Exception:
            return WebHealth(last_error_type="invalid_health_payload").model_dump(mode="json")
    return WebHealth(last_error_type="health_unavailable").model_dump(mode="json")


def host_from_url(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return parsed.netloc or parsed.path.split("/", 1)[0]
