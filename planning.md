# FitFindr - planning.md

> Post-implementation sync: this document has been updated to match the
> actual implementation in `tools.py`, `agent.py`, `app.py`, and `README.md`.
> The original pre-implementation design used a dict return value for
> `suggest_outfit` and a dict-only input for `create_fit_card`; that design is
> superseded. The shipped scaffold uses strings for the LLM-generated outfit
> suggestion and fit-card caption, with a session dict carrying state between
> tools.

---

## Tools

### Tool 1: `search_listings(description, size, max_price)`

**What it does:**
Searches `data/listings.json` for secondhand listings that match the user's
item description, optional size, and optional price ceiling. Results are scored
by keyword overlap so the closest match appears first.

**Input parameters:**
- `description` (`str`): Keywords describing the desired item.
- `size` (`str | None`): Optional size filter. Matching is case-insensitive.
- `max_price` (`float | None`): Optional inclusive price ceiling.

**What it returns:**
Returns `list[dict]`, sorted by relevance. Each listing contains `id`, `title`,
`description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`,
`brand`, and `platform`. Returns an empty list when nothing matches.

**What happens if it fails or returns nothing:**
The planning loop retries with looser filters: first removing size, then raising
the price limit by 50 percent, then removing price and size filters. If all
attempts fail, the agent sets `session["error"]` and stops before calling the
LLM tools.

---

### Tool 2: `suggest_outfit(new_item, wardrobe, trend_tags=None, style_profile=None)`

**What it does:**
Uses the LLM to suggest one or two outfit ideas pairing the thrifted item with
the user's wardrobe. If no wardrobe is available, it uses either saved style
profile memory or general styling advice.

**Input parameters:**
- `new_item` (`dict`): A listing returned by `search_listings`.
- `wardrobe` (`dict`): A dict with an `items` list. May be empty.
- `trend_tags` (`list | None`): Optional trend tags from `get_trending_styles`.
- `style_profile` (`dict | None`): Optional saved style profile used when the
  wardrobe is empty.

**What it returns:**
Returns a non-empty `str` outfit suggestion. If no wardrobe is provided, the
string starts with either:
- `(No wardrobe provided - suggestion is based on general styling advice)`, or
- `(Based on your saved style profile - no wardrobe provided this session)`.

**What happens if it fails or returns nothing:**
If the LLM returns an empty, malformed, or unusably short response, or if the
LLM call raises due to timeout/rate limiting, the tool returns a deterministic
fallback outfit suggestion using the listing, wardrobe items, trend tags, and
style profile already available. It does not return an empty string.

---

### Tool 3: `create_fit_card(outfit, new_item)`

**What it does:**
Uses the LLM to turn the outfit suggestion into a short social-caption style
fit card that references the listing title, price, and platform.

**Input parameters:**
- `outfit` (`str`): The outfit suggestion returned by `suggest_outfit`.
- `new_item` (`dict`): The selected listing.

**What it returns:**
Returns a `str` caption. If the LLM caption is empty, too short, or missing
required listing context, the tool returns a deterministic fallback caption.

**What happens if it fails or returns nothing:**
If `outfit` itself is empty or whitespace-only, the tool returns an error string
starting with `Error:` so the planning loop can skip that item and try the next
listing. LLM failures use the fallback caption path instead of raising.

---

### Stretch Tool: `compare_price(new_item)`

**What it does:**
Compares the selected item's price against listings in the same category with
overlapping style tags.

**Input parameters:**
- `new_item` (`dict`): The selected listing.

**What it returns:**
Returns a dict with `comparable_count`, `avg_comparable_price`,
`price_diff_pct`, `verdict`, and `assessment`.

---

### Stretch Tool: `get_trending_styles(category)`

**What it does:**
Finds frequently occurring style tags in the mock dataset for the selected
category and, when available, re-ranks them with Google Trends.

**Input parameters:**
- `category` (`str | None`): Category to scope trend analysis.

**What it returns:**
Returns a dict with `trending_styles`, `hot_category`, and `data_source`.

---

## Planning Loop

The agent uses a sequential tool chain with fallback iteration:

1. Parse the natural-language query with regex to extract `description`, `size`,
   and `max_price`.
2. Call `search_listings`.
3. If no exact results are found, retry with progressively looser constraints.
4. If results exist, compute trend info and price comparison for the top result.
5. Iterate through listings until one item produces both an outfit suggestion
   and a fit card.
6. For each candidate listing, call `suggest_outfit`, then `create_fit_card`.
7. If `create_fit_card` returns an `Error:` string or a tool exception occurs,
   move to the next listing.
8. Stop on the first successful fit card and save the style profile.
9. If all listings fail, return a plain-text summary of available listings in
   `session["error"]`.

Regex parsing is used for structured extraction because the patterns are small
and deterministic. The LLM is reserved for outfit styling and caption writing.

---

## State Management

All state lives in a session dict created by `_new_session(query, wardrobe)` in
`agent.py`. No global state is used for the active interaction.

| Key | Type | Purpose |
|---|---|---|
| `query` | `str` | Original user query |
| `parsed` | `dict` | Parsed `description`, `size`, and `max_price` |
| `search_results` | `list[dict]` | Listings returned by search or retry |
| `selected_item` | `dict | None` | Current listing being styled |
| `wardrobe` | `dict` | User wardrobe passed into the run |
| `outfit_suggestion` | `str | None` | Output from `suggest_outfit` |
| `fit_card` | `str | None` | Output from `create_fit_card` |
| `error` | `str | None` | User-facing failure message |
| `retry_info` | `str | None` | Description of loosened search constraints |
| `price_comparison` | `dict | None` | Output from `compare_price` |
| `trend_info` | `dict | None` | Output from `get_trending_styles` |
| `profile_used` | `bool` | Whether saved style memory shaped the outfit |

Each tool receives values from the session dict or from the current listing in
the planning loop. Values are not re-parsed from the raw query after step 1.

---

## Error Handling

| Tool | Failure mode | Agent response |
|---|---|---|
| `search_listings` | No exact results | Retry with looser filters; if all retries fail, set `session["error"]` and stop. |
| `suggest_outfit` | Empty wardrobe | Use saved style profile when available; otherwise prepend the generic styling note. |
| `suggest_outfit` | Empty, malformed, too-short, timeout, or rate-limit LLM response | Return deterministic fallback outfit text from listing/wardrobe/profile/trend context. |
| `create_fit_card` | Empty or whitespace outfit input | Return an `Error:` string so the planning loop can skip to the next listing. |
| `create_fit_card` | Empty, malformed, too-short, timeout, or rate-limit LLM caption response | Return deterministic fallback caption including item title, price, and platform. |
| Planning loop | All listings fail to produce a fit card | Set `session["error"]` with a plain-text summary of found listings. |

---

## Architecture

```text
User query + wardrobe
        |
        v
_parse_query()
        |
        v
search_listings(description, size, max_price)
        |
        +-- no results --> retry search with looser filters
        |                         |
        |                         +-- still no results --> session["error"] --> stop
        |
        v
trend_info = get_trending_styles(selected category)
price_comparison = compare_price(top listing)
        |
        v
for each listing:
        |
        +--> suggest_outfit(item, wardrobe, trend_tags, style_profile)
        |
        +--> create_fit_card(outfit_suggestion, item)
        |
        +-- success --> save_style_profile(session) --> return session
        |
        +-- failure --> try next listing
        |
        v
all failed --> session["error"] with listing summary
```

---

## AI Tool Plan and Verification

**Tool implementation plan:**
- Use AI assistance to implement each required tool against the contracts above.
- Verify `search_listings` deterministically with dataset-based tests.
- Verify `suggest_outfit` and `create_fit_card` with mocked Groq responses so
  tests do not require live API access.
- Keep the README and this planning document synchronized with any interface
  changes.

**Defensive LLM testing plan:**
- Mock normal LLM strings for happy-path tests.
- Mock empty strings to confirm deterministic fallbacks.
- Mock too-short prompt-drift strings such as `OK`.
- Mock timeout/rate-limit style exceptions.
- Assert the tools return useful strings instead of empty output or uncaught
  exceptions.

---

## A Complete Interaction

**Example query:**
`"I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers."`

**Step 1: parse query**
The agent extracts:
- `description="vintage graphic tee"`
- `size=None`
- `max_price=30.0`

**Step 2: search**
The agent calls:

```python
search_listings("vintage graphic tee", size=None, max_price=30.0)
```

The returned list is stored in `session["search_results"]`.

**Step 3: context tools**
For the top listing, the agent calls:

```python
get_trending_styles(item["category"])
compare_price(item)
```

The results are stored in `session["trend_info"]` and
`session["price_comparison"]`.

**Step 4: outfit**
The agent calls:

```python
suggest_outfit(item, wardrobe, trend_tags=trend_info["trending_styles"])
```

The string result is stored in `session["outfit_suggestion"]`.

**Step 5: fit card**
The agent calls:

```python
create_fit_card(session["outfit_suggestion"], item)
```

The caption string is stored in `session["fit_card"]`.

**Final output to user:**
The Gradio UI displays the top listing, outfit idea, fit card caption, price
analysis, and style context panels.

---

## Stretch Features

### Price Comparison

`compare_price(new_item)` benchmarks the selected item against comparable
listings in the same category with overlapping style tags. It returns a verdict
such as `great deal`, `fair price`, `slightly high`, or `overpriced`.

### Style Profile Memory

After each successful run, `save_style_profile(session)` stores selected item
style tags, categories, price range, and interaction count in
`style_profile.json`. Future empty-wardrobe runs can use this profile as styling
context.

### Trend Awareness

`get_trending_styles(category)` computes top style tags from the local listing
dataset and optionally re-ranks them with Google Trends. These tags are passed
into `suggest_outfit`.

### Retry Logic

When exact search results fail, the agent retries by removing size, increasing
the price limit, and finally removing price/size filters. Successful retries set
`session["retry_info"]` so the UI can explain what changed.

---

## Spec Reflection

The original planning document helped define the tool boundaries and error
handling before implementation. The main divergence was the `suggest_outfit`
contract: the initial plan described a dict containing `new_item`, `wardrobe`,
and `style_notes`, while the provided scaffold and finished UI consume a plain
string outfit suggestion. The final implementation follows the scaffold because
that keeps the Gradio panels simple and keeps the session dict as the single
place where item, wardrobe, outfit, fit-card, trend, and price state are joined.

This document now reflects that final design instead of preserving the old
dict-based interface as if it were still active.
