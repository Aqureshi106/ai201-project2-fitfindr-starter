"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform
    """
    listings = load_listings()

    # Filter by price ceiling (inclusive)
    if max_price is not None:
        listings = [l for l in listings if l["price"] <= max_price]

    # Filter by size — case-insensitive substring match so "M" matches "S/M"
    if size is not None:
        size_lower = size.lower()
        listings = [l for l in listings if size_lower in l["size"].lower()]

    # Score each listing by keyword overlap with description
    keywords = set(description.lower().split())

    def _score(listing: dict) -> int:
        searchable = " ".join([
            listing["title"],
            listing["description"],
            listing["category"],
            " ".join(listing.get("style_tags", [])),
        ]).lower()
        return sum(1 for kw in keywords if kw in searchable)

    scored = [(_score(l), l) for l in listings]
    scored = [(s, l) for s, l in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)

    return [l for _, l in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offers general styling advice for the item
        and prepends a note so the caller knows the suggestion is generic.
    """
    client = _get_groq_client()

    item_desc = (
        f"Item: {new_item['title']}\n"
        f"Category: {new_item['category']}\n"
        f"Style tags: {', '.join(new_item.get('style_tags', []))}\n"
        f"Colors: {', '.join(new_item.get('colors', []))}\n"
        f"Description: {new_item.get('description', '')}"
    )

    wardrobe_items = wardrobe.get("items", [])
    is_generic = not wardrobe_items

    if is_generic:
        prompt = (
            f"A user is considering buying this thrifted item:\n{item_desc}\n\n"
            "They haven't shared their wardrobe. Suggest 1–2 general outfit ideas: "
            "what kinds of pieces pair well with this item, what vibe or aesthetic it suits, "
            "and one specific styling tip. Keep it casual and specific."
        )
    else:
        wardrobe_text = "\n".join(
            f"- {item['name']} ({item['category']}, "
            f"tags: {', '.join(item.get('style_tags', []))})"
            for item in wardrobe_items
        )
        prompt = (
            f"A user is considering buying this thrifted item:\n{item_desc}\n\n"
            f"Their wardrobe includes:\n{wardrobe_text}\n\n"
            "Suggest 1–2 specific outfit combinations using the new item and named pieces "
            "from their wardrobe. Be specific about which wardrobe pieces to pair and how "
            "to style the overall look. Keep it casual and practical."
        )

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )

    suggestion = response.choices[0].message.content.strip()

    if is_generic:
        suggestion = (
            "(No wardrobe provided — suggestion is based on general styling advice)\n\n"
            + suggestion
        )

    return suggestion


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, returns a descriptive error message
        string — does NOT raise an exception.

    The caption:
    - Feels casual and authentic (like a real OOTD post)
    - Mentions the item name, price, and platform naturally (once each)
    - Captures the outfit vibe in specific terms
    """
    if not outfit or not outfit.strip():
        return (
            f"Error: no outfit suggestion available for "
            f"'{new_item.get('title', 'this item')}' — cannot generate a fit card."
        )

    client = _get_groq_client()

    prompt = (
        f"Write a 2–4 sentence Instagram caption for this thrifted outfit.\n\n"
        f"Thrifted item: {new_item['title']} — ${new_item['price']:.2f} "
        f"on {new_item['platform']}\n"
        f"Outfit: {outfit}\n\n"
        "The caption should:\n"
        "- Feel casual and authentic, like a real OOTD post (not a product description)\n"
        "- Mention the item name, price, and platform naturally, each exactly once\n"
        "- Capture the outfit vibe in specific, visual terms\n"
        "- Sound fresh and different for different outfits\n"
        "Do not use hashtags or emojis."
    )

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
    )

    return response.choices[0].message.content.strip()
