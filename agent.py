"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parser ──────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract description, size, and max_price from a natural language query
    using regex. Chosen over LLM parsing because it is deterministic and
    requires no API call for this structured extraction task.

    Returns a dict with keys: description (str), size (str|None), max_price (float|None).
    """
    # Extract price: "under $30", "under 30", "< $30"
    price_match = re.search(r'\bunder\s+\$?(\d+(?:\.\d+)?)', query, re.IGNORECASE)
    max_price = float(price_match.group(1)) if price_match else None

    # Extract size: requires the word "size" to avoid false positives on S/M/L
    size_match = re.search(r'\bsize\s+([A-Za-z0-9/]+)', query, re.IGNORECASE)
    size = size_match.group(1).upper() if size_match else None

    # Build description by removing price and size phrases from the query
    desc = query
    if price_match:
        desc = desc[: price_match.start()] + desc[price_match.end() :]
    if size_match:
        # Also strip an optional "in " that may precede "size"
        start = size_match.start()
        if start >= 3 and desc[start - 3 : start].lower() == "in ":
            start -= 3
        desc = desc[:start] + desc[size_match.end() :]

    # Strip common leading filler phrases
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

    # Drop short stop words that add noise to keyword scoring
    stop_words = {"a", "an", "the", "for", "in", "at", "on", "with", "and", "or"}
    desc = " ".join(w for w in desc.split() if w.lower() not in stop_words)

    desc = re.sub(r"\s+", " ", desc).strip().strip(",").strip()

    return {"description": desc, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.
    """
    # Step 1: Initialize session
    session = _new_session(query, wardrobe)

    # Step 2: Parse the query into structured parameters
    parsed = _parse_query(query)
    session["parsed"] = parsed

    # Guard: if no description could be extracted, ask the user to clarify
    if not parsed["description"]:
        session["error"] = (
            "I couldn't understand what you're looking for. "
            "Try something like: 'vintage graphic tee under $30'."
        )
        return session

    # Step 3: Search for matching listings — branch on the result
    results = search_listings(
        description=parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )
    session["search_results"] = results

    if not results:
        price_str = (
            f"under ${parsed['max_price']:.0f}" if parsed["max_price"] else "any price"
        )
        session["error"] = (
            f"No listings found for '{parsed['description']}' at {price_str}. "
            "Try a broader term (e.g. 'graphic tee' instead of 'vintage graphic tee') "
            "or raise your price limit."
        )
        return session

    # Steps 4–6: Iterate through listings until one produces a successful fit card.
    # current_index tracks position in the results list; increments on tool failure.
    for current_index, item in enumerate(results):
        session["selected_item"] = item

        # Step 5: Suggest an outfit for this listing
        try:
            outfit = suggest_outfit(item, wardrobe)
        except Exception:
            session["outfit_suggestion"] = None
            continue  # try the next listing

        session["outfit_suggestion"] = outfit

        # Step 6: Create the fit card from the outfit suggestion
        try:
            fit_card = create_fit_card(outfit, item)
        except Exception:
            session["outfit_suggestion"] = None
            continue  # try the next listing

        # Guard: create_fit_card returns an error string when outfit is empty
        if fit_card.lower().startswith("error:"):
            session["outfit_suggestion"] = None
            continue

        session["fit_card"] = fit_card
        return session  # at least one card succeeded — done

    # All listings exhausted without a successful fit card
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
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
