"""
tests/test_tools.py

Pytest tests for each FitFindr tool.
At least one test per failure mode defined in planning.md.

Run from the project root:
    pytest tests/
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Make the project root importable regardless of where pytest is invoked from
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import create_fit_card, search_listings, suggest_outfit


# ── Shared fixtures ───────────────────────────────────────────────────────────

SAMPLE_ITEM = {
    "id": "lst_006",
    "title": "Graphic Tee — 2003 Tour Bootleg Style",
    "description": "Vintage-style bootleg tee with faded graphic. Slightly boxy fit.",
    "category": "tops",
    "style_tags": ["graphic tee", "vintage", "grunge", "streetwear"],
    "size": "L",
    "condition": "good",
    "price": 24.00,
    "colors": ["black"],
    "brand": None,
    "platform": "depop",
}

SAMPLE_WARDROBE = {
    "items": [
        {
            "id": "w_001",
            "name": "Baggy straight-leg jeans, dark wash",
            "category": "bottoms",
            "colors": ["dark blue"],
            "style_tags": ["denim", "streetwear", "baggy"],
        },
        {
            "id": "w_007",
            "name": "Chunky white sneakers",
            "category": "shoes",
            "colors": ["white"],
            "style_tags": ["sneakers", "chunky", "streetwear"],
        },
    ]
}

EMPTY_WARDROBE = {"items": []}


def _mock_groq(response_text: str):
    """Return a mock Groq client that returns response_text from any LLM call."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = response_text
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


def _mock_groq_error(exc: Exception):
    """Return a mock Groq client whose LLM call raises exc."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = exc
    return mock_client


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def test_search_returns_results():
    """Happy path: a broad query with a generous price should return matches."""
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    """Failure mode: impossible query returns empty list, not an exception."""
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    """Price ceiling is enforced — every result must be at or below max_price."""
    results = search_listings("jacket", size=None, max_price=30)
    assert all(item["price"] <= 30 for item in results)


def test_search_size_filter():
    """Size filter matches case-insensitively ('l' matches 'L', 'XL', 'One Size / Oversized L')."""
    results = search_listings("tee", size="L", max_price=None)
    assert all("l" in item["size"].lower() for item in results)


def test_search_size_none_skips_filter():
    """size=None should not narrow results — returns at least as many as a strict filter."""
    all_results = search_listings("vintage", size=None, max_price=None)
    filtered = search_listings("vintage", size="XS", max_price=None)
    assert len(all_results) >= len(filtered)


def test_search_sorted_by_relevance():
    """Results with more keyword matches should appear before weaker matches."""
    results = search_listings("vintage graphic tee", size=None, max_price=None)
    assert len(results) > 1
    first_title = results[0]["title"].lower()
    assert "graphic" in first_title or "tee" in first_title


def test_search_returns_all_required_keys():
    """Every returned listing must contain the fields defined in planning.md."""
    results = search_listings("vintage", size=None, max_price=None)
    assert len(results) > 0
    required = {"id", "title", "description", "category", "style_tags",
                "size", "condition", "price", "colors", "brand", "platform"}
    for item in results:
        assert required.issubset(item.keys())


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def test_suggest_outfit_returns_string():
    """Happy path: returns a non-empty string for a normal item + wardrobe."""
    with patch("tools._get_groq_client", return_value=_mock_groq("Wear the tee with baggy jeans.")):
        result = suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)
    assert isinstance(result, str)
    assert len(result) > 0


def test_suggest_outfit_empty_wardrobe_prepends_note():
    """Failure mode: empty wardrobe — response must start with the generic note."""
    with patch("tools._get_groq_client", return_value=_mock_groq("Try straight-leg jeans.")):
        result = suggest_outfit(SAMPLE_ITEM, EMPTY_WARDROBE)
    assert isinstance(result, str)
    assert result.startswith("(No wardrobe provided")


def test_suggest_outfit_empty_wardrobe_does_not_raise():
    """Failure mode: empty wardrobe must not raise an exception."""
    with patch("tools._get_groq_client", return_value=_mock_groq("General styling advice.")):
        result = suggest_outfit(SAMPLE_ITEM, EMPTY_WARDROBE)
    assert result  # truthy — not empty, not None


def test_suggest_outfit_missing_items_key_treated_as_empty():
    """Wardrobe dict with no 'items' key is treated the same as an empty wardrobe."""
    with patch("tools._get_groq_client", return_value=_mock_groq("General advice.")):
        result = suggest_outfit(SAMPLE_ITEM, {})
    assert result.startswith("(No wardrobe provided")


def test_suggest_outfit_uses_wardrobe_when_provided():
    """Non-empty wardrobe should NOT prepend the generic note."""
    with patch("tools._get_groq_client", return_value=_mock_groq("Pair with your baggy jeans.")):
        result = suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)
    assert not result.startswith("(No wardrobe provided")


def test_suggest_outfit_empty_llm_response_returns_fallback():
    """Malformed LLM output: empty content should still produce useful styling text."""
    with patch("tools._get_groq_client", return_value=_mock_groq("   ")):
        result = suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)
    assert isinstance(result, str)
    assert len(result.strip()) > 0
    assert SAMPLE_ITEM["title"] in result
    assert "Baggy straight-leg jeans" in result


def test_suggest_outfit_too_short_llm_response_returns_fallback():
    """Malformed LLM output: terse prompt drift like 'OK' should not be surfaced."""
    with patch("tools._get_groq_client", return_value=_mock_groq("OK")):
        result = suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)
    assert result != "OK"
    assert SAMPLE_ITEM["title"] in result


def test_suggest_outfit_llm_exception_returns_fallback():
    """External-service failure: timeouts/rate limits should degrade to fallback advice."""
    with patch("tools._get_groq_client", return_value=_mock_groq_error(TimeoutError("timed out"))):
        result = suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)
    assert isinstance(result, str)
    assert len(result.strip()) > 0
    assert SAMPLE_ITEM["title"] in result


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def test_create_fit_card_returns_string():
    """Happy path: valid outfit + item returns a non-empty string."""
    with patch("tools._get_groq_client", return_value=_mock_groq("Found this tee on depop for $24.")):
        result = create_fit_card("Tuck the tee into baggy jeans.", SAMPLE_ITEM)
    assert isinstance(result, str)
    assert len(result) > 0


def test_create_fit_card_empty_outfit_returns_error_string():
    """Failure mode: empty outfit string returns an error message, not an exception."""
    result = create_fit_card("", SAMPLE_ITEM)
    assert isinstance(result, str)
    assert "error" in result.lower() or "no outfit" in result.lower()


def test_create_fit_card_whitespace_outfit_returns_error_string():
    """Failure mode: whitespace-only outfit string is treated the same as empty."""
    result = create_fit_card("   ", SAMPLE_ITEM)
    assert isinstance(result, str)
    assert "error" in result.lower() or "no outfit" in result.lower()


def test_create_fit_card_empty_outfit_does_not_raise():
    """Failure mode: empty outfit must not raise — agent relies on a string return."""
    try:
        result = create_fit_card("", SAMPLE_ITEM)
    except Exception as exc:
        pytest.fail(f"create_fit_card raised on empty outfit: {exc}")


def test_create_fit_card_whitespace_outfit_does_not_raise():
    """Failure mode: whitespace outfit must not raise."""
    try:
        result = create_fit_card("   ", SAMPLE_ITEM)
    except Exception as exc:
        pytest.fail(f"create_fit_card raised on whitespace outfit: {exc}")


def test_create_fit_card_empty_llm_response_returns_fallback_caption():
    """Malformed LLM output: empty caption content should fall back to a usable card."""
    outfit = "Tuck the tee into baggy jeans and finish with chunky sneakers."
    with patch("tools._get_groq_client", return_value=_mock_groq("   ")):
        result = create_fit_card(outfit, SAMPLE_ITEM)
    assert isinstance(result, str)
    assert not result.lower().startswith("error:")
    assert SAMPLE_ITEM["title"] in result
    assert "$24.00" in result
    assert SAMPLE_ITEM["platform"] in result


def test_create_fit_card_too_short_llm_response_returns_fallback_caption():
    """Malformed LLM output: a non-instruction-following response should be replaced."""
    outfit = "Tuck the tee into baggy jeans and finish with chunky sneakers."
    with patch("tools._get_groq_client", return_value=_mock_groq("OK")):
        result = create_fit_card(outfit, SAMPLE_ITEM)
    assert result != "OK"
    assert SAMPLE_ITEM["title"] in result
    assert "$24.00" in result


def test_create_fit_card_llm_exception_returns_fallback_caption():
    """External-service failure: timeout/rate-limit style exceptions return a fallback card."""
    outfit = "Tuck the tee into baggy jeans and finish with chunky sneakers."
    with patch("tools._get_groq_client", return_value=_mock_groq_error(TimeoutError("timed out"))):
        result = create_fit_card(outfit, SAMPLE_ITEM)
    assert isinstance(result, str)
    assert not result.lower().startswith("error:")
    assert SAMPLE_ITEM["title"] in result
