from autotrace.analyzer import deterministic_diagnosis
from autotrace.models import INTERVALS, SiteCreate


def test_supported_intervals():
    assert INTERVALS == {5: 300, 15: 900, 60: 3600}
    assert SiteCreate(name="Demo", url="https://example.com", interval_minutes=15).interval_seconds() == 900


def test_http_failure_diagnosis_is_actionable():
    result = deterministic_diagnosis(
        {
            "page_url": "https://example.com",
            "findings": [
                {
                    "kind": "http_error",
                    "message": "Request returned HTTP 500",
                }
            ],
        }
    )
    assert "HTTP error" in result["summary"]
    assert result["reproduction_steps"]
    assert result["fix_suggestion"]