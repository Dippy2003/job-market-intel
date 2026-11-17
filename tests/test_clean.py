"""Title and location cleaning. No database."""
from pipeline.clean import normalize_location
from scrapers.base import normalize_title


def test_title_keeps_skill_in_parentheses():
    assert normalize_title("Team Leader – Web Development (WordPress)") == (
        "team leader web development wordpress"
    )


def test_title_drops_shift_and_experience_noise():
    assert normalize_title("Customer Support Specialist (US Shift)") == "customer support specialist"
    assert normalize_title("Instructor (Temporary)") == "instructor"
    assert (
        normalize_title("React Web Developer (Minimum 1 Year of React Development Experience)")
        == "react web developer"
    )
    assert (
        normalize_title("Associate QA Engineer with one year of hands-on QA experience")
        == "associate qa engineer"
    )


def test_title_expands_senior_and_keeps_dotnet():
    assert normalize_title("Sr. Software Engineer - .NET") == "senior software engineer .net"


def test_location_labels():
    assert normalize_location("  colombo ") == "Colombo"
    assert normalize_location("hybrid / remote") == "Hybrid"
    assert normalize_location("Colombo, Jaffna, Colombo") == "Colombo, Jaffna"
    assert normalize_location(None) is None
    assert normalize_location("   ") is None
