"""
tools.py

The three required FitFindr tools plus two stretch-feature tools.

Tools:
    search_listings(description, size, max_price)              → list[dict]
    suggest_outfit(new_item, wardrobe, trend_tags, style_profile) → str
    create_fit_card(outfit, new_item)                          → str
    compare_price(new_item)                                    → dict   [stretch]
    get_trending_styles(category)                              → dict   [stretch]
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


def _extract_llm_text(response) -> str:
    """Safely pull text from a Groq chat completion response."""
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        return ""
    if not isinstance(content, str):
        return ""
    return content.strip()


def _has_enough_words(text: str, minimum: int) -> bool:
    """Treat ultra-short LLM replies as unusable model drift."""
    return len(text.split()) >= minimum


def _fallback_outfit_suggestion(
    new_item: dict,
    wardrobe: dict,
    context_note: str = "",
    trend_tags: list | None = None,
    style_profile: dict | None = None,
) -> str:
    """Build a useful outfit suggestion when the LLM response is unavailable."""
    title = new_item.get("title", "this thrifted piece")
    category = new_item.get("category", "piece")
    color_text = ", ".join(new_item.get("colors", [])) or "the item's main color"
    tag_text = ", ".join(new_item.get("style_tags", [])[:3]) or category
    trend_text = ""
    if trend_tags:
        trend_text = f" The {trend_tags[0]} trend is an easy reference point here."

    wardrobe_items = wardrobe.get("items", []) if isinstance(wardrobe, dict) else []
    if wardrobe_items:
        piece_names = [
            item.get("name", item.get("category", "wardrobe piece"))
            for item in wardrobe_items[:3]
        ]
        pieces = ", ".join(piece_names)
        suggestion = (
            f"Pair {title} with {pieces}. Keep the look grounded in {color_text}, "
            f"then echo the {tag_text} vibe with one simple accessory or shoe choice."
            f"{trend_text}"
        )
    else:
        profile_styles = (style_profile or {}).get("preferred_styles", [])
        style_anchor = ", ".join(profile_styles[:3]) if profile_styles else tag_text
        suggestion = (
            f"Build the outfit around {title} as the main {category} piece. "
            f"Use relaxed denim, clean sneakers, or a simple layer that supports "
            f"the {style_anchor} feel without competing with the item."
            f"{trend_text}"
        )

    return context_note + suggestion


def _fallback_fit_card(outfit: str, new_item: dict) -> str:
    """Build a caption when the LLM caption is empty or malformed."""
    title = new_item.get("title", "this thrifted find")
    price = new_item.get("price")
    price_text = f"${price:.2f}" if isinstance(price, (int, float)) else "a thrifted price"
    platform = new_item.get("platform", "a secondhand platform")
    outfit_summary = " ".join(outfit.split())[:160].rstrip(".")
    return (
        f"{title} for {price_text} on {platform} is the anchor piece for this look. "
        f"{outfit_summary}."
    )


def _fit_card_text_is_usable(text: str, new_item: dict) -> bool:
    """Check that a caption has enough detail and names the required listing context."""
    if not _has_enough_words(text, 8):
        return False
    price = new_item.get("price")
    price_text = f"${price:.2f}" if isinstance(price, (int, float)) else ""
    platform = str(new_item.get("platform", "")).lower()
    if price_text and price_text not in text:
        return False
    if platform and platform not in text.lower():
        return False
    return True


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

    if max_price is not None:
        listings = [l for l in listings if l["price"] <= max_price]

    if size is not None:
        size_lower = size.lower()
        listings = [l for l in listings if size_lower in l["size"].lower()]

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

def suggest_outfit(
    new_item: dict,
    wardrobe: dict,
    trend_tags: list | None = None,
    style_profile: dict | None = None,
) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item:      A listing dict (the item the user is considering buying).
        wardrobe:      A wardrobe dict with an 'items' key. May be empty.
        trend_tags:    Optional list of trending style tags for the item's category.
                       When provided, the LLM is prompted to incorporate them where natural.
        style_profile: Optional saved style profile dict (preferred_styles, etc.).
                       Used as wardrobe substitute when wardrobe is empty and profile
                       has accumulated preferences from past interactions.

    Returns:
        A non-empty string with outfit suggestions.
        Prepends a context note when wardrobe is empty or profile is substituted.
    """
    item_desc = (
        f"Item: {new_item['title']}\n"
        f"Category: {new_item['category']}\n"
        f"Style tags: {', '.join(new_item.get('style_tags', []))}\n"
        f"Colors: {', '.join(new_item.get('colors', []))}\n"
        f"Description: {new_item.get('description', '')}"
    )

    wardrobe_items = wardrobe.get("items", [])
    profile_styles = (style_profile or {}).get("preferred_styles", [])
    is_generic = not wardrobe_items

    trend_line = ""
    if trend_tags:
        trend_line = (
            f"\n\nCurrently trending styles for {new_item['category']}: "
            f"{', '.join(trend_tags)}. Where it fits naturally, reference these trends."
        )

    if is_generic and profile_styles:
        prompt = (
            f"A user is considering buying this thrifted item:\n{item_desc}\n\n"
            f"Based on their style history, they gravitate toward: "
            f"{', '.join(profile_styles[:8])}. "
            "Suggest 1–2 outfit ideas that match their established style. "
            "Name specific piece types that would suit them and how to style the look."
            + trend_line
        )
        context_note = (
            "(Based on your saved style profile — no wardrobe provided this session)\n\n"
        )
    elif is_generic:
        prompt = (
            f"A user is considering buying this thrifted item:\n{item_desc}\n\n"
            "They haven't shared their wardrobe. Suggest 1–2 general outfit ideas: "
            "what kinds of pieces pair well with this item, what vibe it suits, "
            "and one specific styling tip. Keep it casual and specific."
            + trend_line
        )
        context_note = (
            "(No wardrobe provided — suggestion is based on general styling advice)\n\n"
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
            "from their wardrobe. Be specific about which pieces to pair and how to style "
            "the overall look. Keep it casual and practical."
            + trend_line
        )
        context_note = ""

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        suggestion = _extract_llm_text(response)
    except Exception:
        suggestion = ""

    if not _has_enough_words(suggestion, 5):
        return _fallback_outfit_suggestion(
            new_item,
            wardrobe,
            context_note=context_note,
            trend_tags=trend_tags,
            style_profile=style_profile,
        )

    if is_generic:
        suggestion = context_note + suggestion

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
    """
    if not outfit or not outfit.strip():
        return (
            f"Error: no outfit suggestion available for "
            f"'{new_item.get('title', 'this item')}' — cannot generate a fit card."
        )

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

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
        )
        caption = _extract_llm_text(response)
    except Exception:
        caption = ""

    if not _fit_card_text_is_usable(caption, new_item):
        return _fallback_fit_card(outfit, new_item)

    return caption


# ── Stretch Tool: compare_price ───────────────────────────────────────────────

def compare_price(new_item: dict) -> dict:
    """
    Compare new_item's price against comparable listings in the dataset.

    Comparables are defined as listings that share the same category AND
    have at least one overlapping style_tag with new_item. The average price
    of comparables is used as the benchmark.

    Args:
        new_item: A listing dict from search_listings.

    Returns:
        A dict with:
            comparable_count (int): number of comparable listings found
            avg_comparable_price (float | None): average price of comparables
            price_diff_pct (float | None): % difference vs. average (negative = cheaper)
            verdict (str): "great deal", "fair price", "slightly high", "overpriced",
                           or "no comparables"
            assessment (str): human-readable explanation with specific numbers
    """
    listings = load_listings()
    item_id = new_item["id"]
    category = new_item["category"]
    item_tags = set(new_item.get("style_tags", []))
    item_price = new_item["price"]

    comparables = [
        l for l in listings
        if l["id"] != item_id
        and l["category"] == category
        and set(l.get("style_tags", [])) & item_tags
    ]

    if not comparables:
        return {
            "comparable_count": 0,
            "avg_comparable_price": None,
            "price_diff_pct": None,
            "verdict": "no comparables",
            "assessment": (
                f"No comparable {category} listings found in the dataset to benchmark against."
            ),
        }

    avg_price = sum(l["price"] for l in comparables) / len(comparables)
    diff_pct = ((item_price - avg_price) / avg_price) * 100

    if diff_pct <= -20:
        verdict = "great deal"
        assessment = (
            f"At ${item_price:.2f}, this is {abs(diff_pct):.0f}% below the average "
            f"${avg_price:.2f} across {len(comparables)} comparable {category} listing(s). Strong buy."
        )
    elif diff_pct <= 5:
        verdict = "fair price"
        assessment = (
            f"At ${item_price:.2f}, this is priced close to the average "
            f"${avg_price:.2f} across {len(comparables)} comparable {category} listing(s). Fair value."
        )
    elif diff_pct <= 25:
        verdict = "slightly high"
        assessment = (
            f"At ${item_price:.2f}, this is {diff_pct:.0f}% above the average "
            f"${avg_price:.2f} across {len(comparables)} comparable {category} listing(s). "
            "Reasonable, but room to negotiate."
        )
    else:
        verdict = "overpriced"
        assessment = (
            f"At ${item_price:.2f}, this is {diff_pct:.0f}% above the average "
            f"${avg_price:.2f} across {len(comparables)} comparable {category} listing(s). "
            "Consider looking for alternatives."
        )

    return {
        "comparable_count": len(comparables),
        "avg_comparable_price": round(avg_price, 2),
        "price_diff_pct": round(diff_pct, 1),
        "verdict": verdict,
        "assessment": assessment,
    }


# ── Stretch Tool: get_trending_styles ─────────────────────────────────────────

def _rank_by_google_trends(candidate_tags: list[str]) -> list[str] | None:
    """
    Re-rank candidate_tags by 7-day Google Trends interest (Apparel cat=185, US).
    Returns None if the request fails or returns no data, so callers can fall back.
    """
    try:
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl="en-US", tz=360)
        pytrends.build_payload(
            kw_list=candidate_tags,
            cat=185,        # Google Trends: Shopping > Apparel & Accessories
            timeframe="now 7-d",
            geo="US",
        )
        data = pytrends.interest_over_time()
        if data.empty:
            return None
        cols = [c for c in candidate_tags if c in data.columns]
        if not cols:
            return None
        scores = data[cols].mean().sort_values(ascending=False)
        return list(scores.index)
    except Exception:
        return None


def get_trending_styles(category: str | None = None) -> dict:
    """
    Identify trending style tags for a category using a two-step approach:

    Step 1 — local candidate pool: the top-5 style tags by listing count in
    data/listings.json for the given category are used as query keywords.

    Step 2 — Google Trends re-rank: those tags are sent to the Google Trends
    API (Apparel & Accessories category, past 7 days, US) and re-ordered by
    actual search interest. Falls back to local frequency order if the request
    fails or returns no data.

    Args:
        category: Limit trend analysis to one category, or None for all categories.

    Returns:
        A dict with:
            trending_styles (list[str]): top 5 tags ranked by Google Trends
                                         interest (or local frequency on fallback)
            hot_category (str): most-listed category across the full dataset
            data_source (str): what was analyzed and which source ranked the tags
    """
    all_listings = load_listings()
    scoped = (
        [l for l in all_listings if l["category"] == category]
        if category else all_listings
    )

    tag_counts: dict[str, int] = {}
    for listing in scoped:
        for tag in listing.get("style_tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
    candidate_tags = [tag for tag, _ in sorted_tags[:5]]

    cat_counts: dict[str, int] = {}
    for listing in all_listings:
        cat = listing["category"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    hot_category = max(cat_counts, key=cat_counts.get)

    scope_label = f"{category} listings" if category else "all listings"

    google_ranked = _rank_by_google_trends(candidate_tags)
    if google_ranked:
        trending = google_ranked
        data_source = (
            f"Google Trends (past week, Apparel & Accessories) re-ranked from "
            f"{len(scoped)} {scope_label} in data/listings.json"
        )
    else:
        trending = candidate_tags
        data_source = (
            f"Analyzed {len(scoped)} {scope_label} from data/listings.json "
            f"(Google Trends unavailable — using local frequency)"
        )

    return {
        "trending_styles": trending,
        "hot_category": hot_category,
        "data_source": data_source,
    }
