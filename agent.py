"""
agent.py

The FitFindr planning loop. Orchestrates all tools in response to a
natural language user query, passing state between them via a session dict.

Stretch features active:
  - Retry logic: loosens constraints automatically when search returns empty
  - Style profile memory: saves/loads style preferences across interactions
  - Price comparison: runs compare_price on the selected item
  - Trend awareness: injects trending style tags into suggest_outfit
"""

import re

from tools import (
    search_listings,
    suggest_outfit,
    create_fit_card,
    compare_price,
    get_trending_styles,
)
from utils.style_memory import load_style_profile, save_style_profile


# ── query parser ──────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract description, size, and max_price from a natural language query
    using regex. Chosen over LLM parsing because it is deterministic and
    requires no API call for this structured extraction task.
    """
    price_match = re.search(r'\bunder\s+\$?(\d+(?:\.\d+)?)', query, re.IGNORECASE)
    max_price = float(price_match.group(1)) if price_match else None

    size_match = re.search(r'\bsize\s+([A-Za-z0-9/]+)', query, re.IGNORECASE)
    size = size_match.group(1).upper() if size_match else None

    desc = query
    if price_match:
        desc = desc[: price_match.start()] + desc[price_match.end() :]
    if size_match:
        start = size_match.start()
        if start >= 3 and desc[start - 3 : start].lower() == "in ":
            start -= 3
        desc = desc[:start] + desc[size_match.end() :]

    for filler in [
        r"^i'?m\s+looking\s+for\s+",
        r"^i\s+am\s+looking\s+for\s+",
        r"^looking\s+for\s+",
        r"^i\s+want\s+",
        r"^find\s+me\s+",
        r"^i\s+need\s+",
        r"^searching\s+for\s+",
    ]:
        desc = re.sub(filler, "", desc, flags=re.IGNORECASE)

    stop_words = {"a", "an", "the", "for", "in", "at", "on", "with", "and", "or"}
    desc = " ".join(w for w in desc.split() if w.lower() not in stop_words)
    desc = re.sub(r"\s+", " ", desc).strip().strip(",").strip()

    return {"description": desc, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    return {
        "query": query,
        "parsed": {},
        "search_results": [],
        "selected_item": None,
        "wardrobe": wardrobe,
        "outfit_suggestion": None,
        "fit_card": None,
        "error": None,
        # Stretch features
        "retry_info": None,       # str: what constraints were loosened, or None
        "price_comparison": None, # dict from compare_price(), or None
        "trend_info": None,       # dict from get_trending_styles(), or None
        "profile_used": False,    # bool: whether style profile influenced outfit
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.
    """
    session = _new_session(query, wardrobe)

    # Load persisted style profile from previous interactions
    style_profile = load_style_profile()

    # Step 1: Parse the query
    parsed = _parse_query(query)
    session["parsed"] = parsed

    if not parsed["description"]:
        session["error"] = (
            "I couldn't understand what you're looking for. "
            "Try something like: 'vintage graphic tee under $30'."
        )
        return session

    # Step 2: Search listings; on empty result, retry with progressively looser filters
    results = search_listings(
        description=parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )
    session["search_results"] = results

    if not results:
        retry_parts = []

        if parsed["size"]:
            retry = search_listings(
                parsed["description"], size=None, max_price=parsed["max_price"]
            )
            if retry:
                results = retry
                retry_parts.append(f"removed size filter ('{parsed['size']}')")

        if not results and parsed["max_price"]:
            raised = parsed["max_price"] * 1.5
            retry = search_listings(
                parsed["description"], size=None, max_price=raised
            )
            if retry:
                results = retry
                retry_parts.append(f"raised price limit to ${raised:.0f}")

        if not results:
            retry = search_listings(parsed["description"], size=None, max_price=None)
            if retry:
                results = retry
                retry_parts.append("removed all price and size filters")

        if results:
            session["search_results"] = results
            session["retry_info"] = (
                "No exact matches — automatically adjusted search: "
                + ", ".join(retry_parts)
                + ". Showing closest alternative."
            )
        else:
            price_str = (
                f"under ${parsed['max_price']:.0f}" if parsed["max_price"] else "any price"
            )
            session["error"] = (
                f"No listings found for '{parsed['description']}' at {price_str}. "
                "Try a broader term (e.g. 'graphic tee' instead of 'vintage graphic tee') "
                "or raise your price limit."
            )
            return session

    # Step 3: Pre-compute trend info and price comparison for the top result
    trend_info = get_trending_styles(results[0]["category"])
    session["trend_info"] = trend_info
    session["price_comparison"] = compare_price(results[0])

    # Step 4: Iterate through listings until one produces a successful fit card
    for current_index, item in enumerate(results):
        session["selected_item"] = item

        # Update price comparison if we fell back to a different listing
        if current_index > 0:
            session["price_comparison"] = compare_price(item)

        # Determine if style profile will substitute for an empty wardrobe
        wardrobe_items = wardrobe.get("items", [])
        profile_styles = style_profile.get("preferred_styles", [])
        using_profile = not wardrobe_items and bool(profile_styles)
        session["profile_used"] = using_profile

        try:
            outfit = suggest_outfit(
                item,
                wardrobe,
                trend_tags=trend_info["trending_styles"],
                style_profile=style_profile if using_profile else None,
            )
        except Exception:
            session["outfit_suggestion"] = None
            continue

        session["outfit_suggestion"] = outfit

        try:
            fit_card = create_fit_card(outfit, item)
        except Exception:
            session["outfit_suggestion"] = None
            continue

        if fit_card.lower().startswith("error:"):
            session["outfit_suggestion"] = None
            continue

        session["fit_card"] = fit_card

        # Persist style preferences for future interactions
        save_style_profile(session)

        return session

    titles = ", ".join(f"'{r['title']}'" for r in results[:3])
    session["error"] = (
        f"Found {len(results)} listing(s) but couldn't generate a fit card. "
        f"Items available: {titles}."
    )
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    s = run_agent("looking for a vintage graphic tee under $30", get_example_wardrobe())
    if s["error"]:
        print(f"Error: {s['error']}")
    else:
        print(f"Found:         {s['selected_item']['title']}")
        print(f"Price check:   {s['price_comparison']['verdict']} — {s['price_comparison']['assessment']}")
        print(f"Trending:      {', '.join(s['trend_info']['trending_styles'])}")
        print(f"\nOutfit:\n{s['outfit_suggestion']}")
        print(f"\nFit card:\n{s['fit_card']}")

    print("\n\n=== No-results path ===\n")
    s2 = run_agent("designer ballgown size XXS under $5", get_example_wardrobe())
    print(f"Error: {s2['error']}")
    print(f"fit_card is None: {s2['fit_card'] is None}")

    print("\n\n=== Retry logic: denim jacket size XS under $20 ===\n")
    s3 = run_agent("denim jacket size XS under $20", get_example_wardrobe())
    if s3["retry_info"]:
        print(f"Retry triggered: {s3['retry_info']}")
        print(f"Found:           {s3['selected_item']['title']}")
    elif s3["error"]:
        print(f"Error: {s3['error']}")

    print("\n\n=== Style profile memory: interaction 2 (empty wardrobe) ===\n")
    s4 = run_agent("streetwear hoodie under $50", get_empty_wardrobe())
    if s4["error"]:
        print(f"Error: {s4['error']}")
    else:
        print(f"Profile used:  {s4['profile_used']}")
        print(f"Found:         {s4['selected_item']['title']}")
        print(f"\nOutfit (first 300 chars):\n{s4['outfit_suggestion'][:300]}")
