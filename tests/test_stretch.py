"""
tests/test_stretch.py

Pytest tests for the four stretch features:
  - compare_price
  - get_trending_styles
  - Retry logic in run_agent
  - Style profile memory (load / save)
  - suggest_outfit with trend_tags and style_profile parameters

Run from the project root:
    pytest tests/test_stretch.py -v
"""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import compare_price, get_trending_styles, suggest_outfit
from utils.style_memory import load_style_profile, save_style_profile


# ── Shared fixtures ───────────────────────────────────────────────────────────

SAMPLE_ITEM = {
    "id": "lst_006",
    "title": "Graphic Tee — 2003 Tour Bootleg Style",
    "description": "Vintage-style bootleg tee with faded graphic.",
    "category": "tops",
    "style_tags": ["graphic tee", "vintage", "grunge", "streetwear"],
    "size": "L",
    "condition": "good",
    "price": 24.00,
    "colors": ["black"],
    "brand": None,
    "platform": "depop",
}

CHEAP_ITEM = {
    "id": "lst_999",
    "title": "Free Tee",
    "description": "A very cheap tee.",
    "category": "tops",
    "style_tags": ["vintage", "streetwear"],
    "size": "M",
    "condition": "fair",
    "price": 1.00,       # well below any comparable average → "great deal"
    "colors": ["white"],
    "brand": None,
    "platform": "depop",
}

PRICEY_ITEM = {
    "id": "lst_998",
    "title": "Luxury Tee",
    "description": "An expensive tee.",
    "category": "tops",
    "style_tags": ["vintage", "streetwear"],
    "size": "M",
    "condition": "excellent",
    "price": 999.00,     # far above any comparable average → "overpriced"
    "colors": ["black"],
    "brand": None,
    "platform": "depop",
}

SAMPLE_WARDROBE = {
    "items": [
        {
            "id": "w_001",
            "name": "Baggy straight-leg jeans",
            "category": "bottoms",
            "colors": ["dark blue"],
            "style_tags": ["denim", "streetwear", "baggy"],
        }
    ]
}

EMPTY_WARDROBE = {"items": []}


def _mock_groq(text: str):
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = text
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_resp
    return mock_client


# ── compare_price ─────────────────────────────────────────────────────────────

def test_compare_price_returns_required_keys():
    result = compare_price(SAMPLE_ITEM)
    assert set(result.keys()) == {
        "comparable_count", "avg_comparable_price",
        "price_diff_pct", "verdict", "assessment"
    }


def test_compare_price_comparable_count_is_int():
    result = compare_price(SAMPLE_ITEM)
    assert isinstance(result["comparable_count"], int)
    assert result["comparable_count"] >= 0


def test_compare_price_assessment_is_nonempty_string():
    result = compare_price(SAMPLE_ITEM)
    assert isinstance(result["assessment"], str)
    assert len(result["assessment"]) > 0


def test_compare_price_verdict_is_valid():
    valid_verdicts = {"great deal", "fair price", "slightly high", "overpriced", "no comparables"}
    result = compare_price(SAMPLE_ITEM)
    assert result["verdict"] in valid_verdicts


def test_compare_price_finds_comparables_for_real_listing():
    # SAMPLE_ITEM is a tops listing with common style_tags — should have comparables
    result = compare_price(SAMPLE_ITEM)
    assert result["comparable_count"] > 0
    assert result["avg_comparable_price"] is not None
    assert result["price_diff_pct"] is not None


def test_compare_price_great_deal_verdict():
    # $1 item is far below any average for tops — expect "great deal"
    result = compare_price(CHEAP_ITEM)
    assert result["verdict"] == "great deal"
    assert result["price_diff_pct"] < -20


def test_compare_price_overpriced_verdict():
    # $999 item is far above any average for tops — expect "overpriced"
    result = compare_price(PRICEY_ITEM)
    assert result["verdict"] == "overpriced"
    assert result["price_diff_pct"] > 25


def test_compare_price_no_comparables_when_unique_tags():
    # Item with a category + tag combo that matches nothing else
    isolated_item = {
        "id": "lst_isolated",
        "title": "Unique Item",
        "description": "Nothing like this.",
        "category": "tops",
        "style_tags": ["xyzzy_nonexistent_tag"],
        "size": "M",
        "condition": "good",
        "price": 20.00,
        "colors": ["blue"],
        "brand": None,
        "platform": "depop",
    }
    result = compare_price(isolated_item)
    assert result["comparable_count"] == 0
    assert result["verdict"] == "no comparables"
    assert result["avg_comparable_price"] is None


# ── get_trending_styles ───────────────────────────────────────────────────────

def test_get_trending_styles_returns_required_keys():
    result = get_trending_styles()
    assert set(result.keys()) == {"trending_styles", "hot_category", "data_source"}


def test_get_trending_styles_returns_nonempty_list():
    result = get_trending_styles()
    assert isinstance(result["trending_styles"], list)
    assert len(result["trending_styles"]) > 0


def test_get_trending_styles_at_most_five_tags():
    result = get_trending_styles()
    assert len(result["trending_styles"]) <= 5


def test_get_trending_styles_hot_category_is_string():
    result = get_trending_styles()
    assert isinstance(result["hot_category"], str)
    assert len(result["hot_category"]) > 0


def test_get_trending_styles_data_source_mentions_dataset():
    result = get_trending_styles()
    assert "listings" in result["data_source"].lower()


def test_get_trending_styles_scoped_by_category():
    tops_result = get_trending_styles(category="tops")
    shoes_result = get_trending_styles(category="shoes")
    # Different categories should generally produce different trending tags
    assert isinstance(tops_result["trending_styles"], list)
    assert isinstance(shoes_result["trending_styles"], list)
    # Scoped data_source should reference the category
    assert "tops" in tops_result["data_source"]


def test_get_trending_styles_all_categories_broader_than_scoped():
    all_result = get_trending_styles(category=None)
    tops_result = get_trending_styles(category="tops")
    # All-category analysis covers more listings — data_source count should be higher
    all_count = int("".join(c for c in all_result["data_source"] if c.isdigit()) or "0")
    tops_count = int("".join(c for c in tops_result["data_source"] if c.isdigit()) or "0")
    assert all_count >= tops_count


# ── suggest_outfit with trend_tags and style_profile ─────────────────────────

def test_suggest_outfit_with_trend_tags_returns_string():
    trend_tags = ["vintage", "streetwear", "grunge"]
    with patch("tools._get_groq_client", return_value=_mock_groq("Outfit with vintage flair.")):
        result = suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE, trend_tags=trend_tags)
    assert isinstance(result, str)
    assert len(result) > 0


def test_suggest_outfit_profile_note_when_wardrobe_empty_and_profile_provided():
    # When wardrobe is empty but style_profile has preferences, should use profile note
    profile = {"preferred_styles": ["vintage", "streetwear"], "interaction_count": 1}
    with patch("tools._get_groq_client", return_value=_mock_groq("Profile-based suggestion.")):
        result = suggest_outfit(SAMPLE_ITEM, EMPTY_WARDROBE, style_profile=profile)
    assert result.startswith("(Based on your saved style profile")


def test_suggest_outfit_generic_note_when_wardrobe_empty_and_no_profile():
    # No wardrobe, no profile → generic note (original behavior preserved)
    with patch("tools._get_groq_client", return_value=_mock_groq("General advice.")):
        result = suggest_outfit(SAMPLE_ITEM, EMPTY_WARDROBE, style_profile=None)
    assert result.startswith("(No wardrobe provided")


def test_suggest_outfit_generic_note_when_profile_has_no_styles():
    # Profile exists but preferred_styles is empty → falls back to generic note
    empty_profile = {"preferred_styles": [], "interaction_count": 0}
    with patch("tools._get_groq_client", return_value=_mock_groq("General advice.")):
        result = suggest_outfit(SAMPLE_ITEM, EMPTY_WARDROBE, style_profile=empty_profile)
    assert result.startswith("(No wardrobe provided")


def test_suggest_outfit_no_context_note_when_wardrobe_provided():
    # Non-empty wardrobe → no note prefix, regardless of other params
    profile = {"preferred_styles": ["vintage"], "interaction_count": 1}
    trend_tags = ["grunge", "cottagecore"]
    with patch("tools._get_groq_client", return_value=_mock_groq("Wardrobe suggestion.")):
        result = suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE, trend_tags=trend_tags, style_profile=profile)
    assert not result.startswith("(No wardrobe")
    assert not result.startswith("(Based on your saved")


# ── Style profile memory ──────────────────────────────────────────────────────

def test_load_returns_blank_profile_when_no_file(tmp_path):
    fake_path = str(tmp_path / "style_profile.json")
    with patch("utils.style_memory._PROFILE_PATH", fake_path):
        profile = load_style_profile()
    assert profile["preferred_styles"] == []
    assert profile["past_categories"] == []
    assert profile["price_range"] is None
    assert profile["interaction_count"] == 0


def test_save_creates_file_and_stores_tags(tmp_path):
    fake_path = str(tmp_path / "style_profile.json")
    session = {"selected_item": SAMPLE_ITEM}
    with patch("utils.style_memory._PROFILE_PATH", fake_path):
        save_style_profile(session)
        assert os.path.exists(fake_path)
        profile = load_style_profile()
    for tag in SAMPLE_ITEM["style_tags"]:
        assert tag in profile["preferred_styles"]


def test_save_stores_category(tmp_path):
    fake_path = str(tmp_path / "style_profile.json")
    session = {"selected_item": SAMPLE_ITEM}
    with patch("utils.style_memory._PROFILE_PATH", fake_path):
        save_style_profile(session)
        profile = load_style_profile()
    assert SAMPLE_ITEM["category"] in profile["past_categories"]


def test_save_stores_price_range(tmp_path):
    fake_path = str(tmp_path / "style_profile.json")
    session = {"selected_item": SAMPLE_ITEM}
    with patch("utils.style_memory._PROFILE_PATH", fake_path):
        save_style_profile(session)
        profile = load_style_profile()
    assert profile["price_range"] is not None
    assert profile["price_range"]["min"] == SAMPLE_ITEM["price"]
    assert profile["price_range"]["max"] == SAMPLE_ITEM["price"]


def test_save_increments_interaction_count(tmp_path):
    fake_path = str(tmp_path / "style_profile.json")
    session = {"selected_item": SAMPLE_ITEM}
    with patch("utils.style_memory._PROFILE_PATH", fake_path):
        save_style_profile(session)
        save_style_profile(session)
        profile = load_style_profile()
    assert profile["interaction_count"] == 2


def test_save_accumulates_styles_across_interactions(tmp_path):
    fake_path = str(tmp_path / "style_profile.json")
    item_a = {**SAMPLE_ITEM, "id": "a", "style_tags": ["vintage", "grunge"]}
    item_b = {**SAMPLE_ITEM, "id": "b", "style_tags": ["cottagecore", "cozy"]}
    with patch("utils.style_memory._PROFILE_PATH", fake_path):
        save_style_profile({"selected_item": item_a})
        save_style_profile({"selected_item": item_b})
        profile = load_style_profile()
    assert "vintage" in profile["preferred_styles"]
    assert "cottagecore" in profile["preferred_styles"]


def test_save_does_nothing_when_no_selected_item(tmp_path):
    fake_path = str(tmp_path / "style_profile.json")
    with patch("utils.style_memory._PROFILE_PATH", fake_path):
        save_style_profile({"selected_item": None})
        assert not os.path.exists(fake_path)


def test_save_does_not_duplicate_tags(tmp_path):
    fake_path = str(tmp_path / "style_profile.json")
    session = {"selected_item": SAMPLE_ITEM}
    with patch("utils.style_memory._PROFILE_PATH", fake_path):
        save_style_profile(session)
        save_style_profile(session)
        profile = load_style_profile()
    for tag in SAMPLE_ITEM["style_tags"]:
        assert profile["preferred_styles"].count(tag) == 1


# ── Retry logic in run_agent ──────────────────────────────────────────────────

def test_retry_triggers_on_restrictive_size_and_price():
    """Query with impossible size+price combo triggers retry and finds something."""
    from agent import run_agent
    mock_outfit = "Wear the jacket with jeans."
    mock_card = "Found this on poshmark."
    with patch("agent.suggest_outfit", return_value=mock_outfit):
        with patch("agent.create_fit_card", return_value=mock_card):
            session = run_agent("denim jacket size XS under $20", {"items": []})
    assert session["retry_info"] is not None
    assert "adjusted" in session["retry_info"].lower()
    assert session["selected_item"] is not None


def test_retry_info_is_none_on_happy_path():
    """A query that matches on the first attempt should not set retry_info."""
    from agent import run_agent
    mock_outfit = "Pair the tee with jeans."
    mock_card = "Great find on depop."
    with patch("agent.suggest_outfit", return_value=mock_outfit):
        with patch("agent.create_fit_card", return_value=mock_card):
            session = run_agent("vintage graphic tee under $50", {"items": []})
    assert session["retry_info"] is None
    assert session["selected_item"] is not None


def test_retry_exhausted_sets_error():
    """A truly impossible query (no results even with all filters removed) sets error."""
    from agent import run_agent
    session = run_agent("xyzzy nonexistent garment qqqqq", {"items": []})
    assert session["error"] is not None
    assert session["fit_card"] is None


def test_retry_result_stored_in_search_results():
    """After a successful retry, session['search_results'] should contain the retry results."""
    from agent import run_agent
    mock_outfit = "Outfit suggestion."
    mock_card = "Fit card caption."
    with patch("agent.suggest_outfit", return_value=mock_outfit):
        with patch("agent.create_fit_card", return_value=mock_card):
            session = run_agent("denim jacket size XS under $20", {"items": []})
    assert len(session["search_results"]) > 0
