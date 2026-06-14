"""
utils/style_memory.py

Persistent style profile memory. Saves style preferences extracted from
completed interactions to style_profile.json in the project root, and
loads them at the start of the next interaction.

Storage approach: a single JSON file keyed by four fields:
  - preferred_styles: accumulated style_tags from all past selected items
  - past_categories: categories the user has browsed
  - price_range: min/max prices from past successful interactions
  - interaction_count: number of completed interactions
"""

import json
import os

_PROFILE_PATH = os.path.join(os.path.dirname(__file__), "..", "style_profile.json")


def load_style_profile() -> dict:
    """Return the saved style profile, or a blank profile if none exists yet."""
    if not os.path.exists(_PROFILE_PATH):
        return {
            "preferred_styles": [],
            "past_categories": [],
            "price_range": None,
            "interaction_count": 0,
        }
    with open(_PROFILE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_style_profile(session: dict) -> None:
    """
    Extract style preferences from a completed session and persist them.
    Only called after a successful interaction (selected_item is set).
    """
    if not session.get("selected_item"):
        return

    profile = load_style_profile()
    item = session["selected_item"]

    for tag in item.get("style_tags", []):
        if tag not in profile["preferred_styles"]:
            profile["preferred_styles"].append(tag)

    cat = item.get("category")
    if cat and cat not in profile["past_categories"]:
        profile["past_categories"].append(cat)

    price = item.get("price")
    if price is not None:
        if profile["price_range"] is None:
            profile["price_range"] = {"min": price, "max": price}
        else:
            profile["price_range"]["min"] = min(profile["price_range"]["min"], price)
            profile["price_range"]["max"] = max(profile["price_range"]["max"], price)

    profile["interaction_count"] = profile.get("interaction_count", 0) + 1

    with open(_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
