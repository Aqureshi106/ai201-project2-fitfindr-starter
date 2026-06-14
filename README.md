# FitFindr

A secondhand fashion agent that searches mock thrift listings, suggests outfit pairings using the user's wardrobe, and generates a shareable fit card — all from a single natural language query.

## Setup

```bash
# Install dependencies into the project virtual environment
pip install -r requirements.txt
```

Create a `.env` file in the project root with your Groq API key (free at [console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

Run the Gradio UI:

```bash
python app.py
```

Run the CLI test (no UI required):

```bash
python agent.py
```

Run tests:

```bash
pytest tests/
```

---

## Tool Inventory

### `search_listings(description, size, max_price)`

**Purpose:** 
Searches `data/listings.json` for secondhand listings that match the user's item description, optional size, and optional price ceiling. Scores results by keyword overlap so the closest match comes first.

**Inputs:**

| Parameter | Type | Description |
|---|---|---|
| `description` | `str` | Keywords describing the item (e.g. `"vintage graphic tee"`) |
| `size` | `str \| None` | Size to filter by, case-insensitive substring match (`"M"` matches `"S/M"`). `None` skips size filtering. |
| `max_price` | `float \| None` | Maximum price inclusive. `None` skips price filtering. |

**Output:** `list[dict]` — a list of matching listing dicts sorted by relevance score, highest first. Each dict contains: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`. Returns an empty list when nothing matches — never raises.

---

### `suggest_outfit(new_item, wardrobe)`

**Purpose:** 
Uses an LLM to suggest 1–2 complete outfit combinations pairing the new thrifted item with pieces from the user's existing wardrobe. Falls back to general styling advice when the wardrobe is empty.

**Inputs:**

| Parameter | Type | Description |
|---|---|---|
| `new_item` | `dict` | A listing dict from `search_listings` (all fields required for the LLM prompt) |
| `wardrobe` | `dict` | A wardrobe dict with an `items` key containing a list of wardrobe item dicts conforming to `wardrobe_schema.json`. May be empty. |

**Output:** 
`str` — a non-empty string with outfit suggestions. When the wardrobe is empty, the string is prepended with `"(No wardrobe provided — suggestion is based on general styling advice)"` so the caller can detect and communicate the fallback to the user. Never returns an empty string.

---

### `create_fit_card(outfit, new_item)`

**Purpose:** 
Uses an LLM to generate a 2–4 sentence Instagram/TikTok-style caption for the outfit, referencing the item's title, price, and platform naturally. Higher LLM temperature (0.9) produces varied output across different inputs.

**Inputs:**

| Parameter | Type | Description |
|---|---|---|
| `outfit` | `str` | The outfit suggestion string from `suggest_outfit` |
| `new_item` | `dict` | The listing dict for the thrifted item (provides title, price, platform) |

**Output:** 
`str` — a 2–4 sentence caption. If `outfit` is empty or whitespace-only, returns a descriptive error string instead of raising — e.g. `"Error: no outfit suggestion available for 'Item Title' — cannot generate a fit card."`

---

## Planning Loop

The agent uses a **sequential tool chain with fallback iteration**. Here is the decision logic in order:

1. **Parse the query** using regex to extract `description`, `size`, and `max_price`. Stop early and ask for clarification if no description can be extracted.

2. **Call `search_listings`**. If the result is an empty list, set `session["error"]` with a specific message and return immediately — `suggest_outfit` is never called with empty input.

3. **Iterate through listings** starting at index 0. For the current listing, call `suggest_outfit`. If it throws, increment the index and try the next listing.

4. **Call `create_fit_card`** with the outfit string. If it throws or returns an error string, increment the index and retry from step 3 with the next listing.

5. **Terminate on first success** — as soon as one fit card is successfully generated, return the session. If all listings are exhausted without success, set `session["error"]` with a plain-text summary of the items that were found.

Query parsing uses regex rather than an LLM call because it is deterministic, requires no API round-trip, and the patterns are well-defined (`"under $30"`, `"size M"`). The LLM is only invoked for the two tasks that genuinely require natural language generation: outfit suggestion and caption writing.

---

## State Management

All state lives in a single session dict initialized by `_new_session()` and passed through the planning loop. No global variables are used.

| Key | Type | Set by | Used by |
|---|---|---|---|
| `query` | `str` | caller | `_parse_query` |
| `parsed` | `dict` | `_parse_query` | `search_listings` call |
| `search_results` | `list[dict]` | `search_listings` | the for-loop iterator |
| `selected_item` | `dict` | planning loop (current iteration) | `suggest_outfit`, `create_fit_card`, `handle_query` |
| `wardrobe` | `dict` | caller | `suggest_outfit` |
| `outfit_suggestion` | `str` | `suggest_outfit` | `create_fit_card`, `handle_query` |
| `fit_card` | `str` | `create_fit_card` | `handle_query` (displayed in panel 3) |
| `error` | `str \| None` | planning loop on failure | `handle_query` (displayed in panel 1) |

Each tool receives its inputs strictly from session fields set by the previous step — no values are re-parsed from the raw query after step 1, and no values are hardcoded between steps.

---

## Error Handling

### `search_listings` — no results match

**Failure mode:** 
The filtered and scored listing list is empty (query too specific, price too low, or size mismatch).

**Agent response:** 
Sets `session["error"]` to a message naming the description and price limit and suggesting concrete alternatives. Returns the session immediately without calling `suggest_outfit`.

**Concrete example from testing:**

Query: `"designer ballgown size XXS under $5"`

```
session["error"] = "No listings found for 'designer ballgown' at under $5.
Try a broader term (e.g. 'graphic tee' instead of 'vintage graphic tee')
or raise your price limit."
session["fit_card"] = None
```

`suggest_outfit` was not called — confirmed by `session["outfit_suggestion"]` remaining `None`.

---

### `suggest_outfit` — wardrobe is empty or not provided

**Failure mode:** 
`wardrobe["items"]` is an empty list, or the wardrobe dict has no `"items"` key at all.

**Agent response:** 
Calls the LLM with a generic styling prompt instead of a wardrobe-specific one. Prepends the fixed note `"(No wardrobe provided — suggestion is based on general styling advice)"` to the response string so the caller knows the suggestion is general.

**Concrete example from testing:**

```python
result = suggest_outfit(SAMPLE_ITEM, {"items": []})
# result starts with:
# "(No wardrobe provided — suggestion is based on general styling advice)
#
#  Try pairing with straight-leg jeans..."
assert result.startswith("(No wardrobe provided")  # passes
```

The agent never raises and never returns an empty string, so `create_fit_card` always receives usable input.

---

### `create_fit_card` — outfit input is missing or incomplete

**Failure mode:** 
`outfit` is an empty string or contains only whitespace.

**Agent response:** 
Returns a descriptive error string (does not raise). In the planning loop, a return value starting with `"error:"` causes the loop to increment `current_index` and retry with the next listing. If all listings are exhausted, `session["error"]` is set with a plain-text listing summary.

**Concrete example from testing:**

```python
result = create_fit_card("", SAMPLE_ITEM)
# result == "Error: no outfit suggestion available for
#            'Graphic Tee — 2003 Tour Bootleg Style' — cannot generate a fit card."
assert "error" in result.lower()   # passes
assert result is not None           # no exception raised — passes
```

---

## Spec Reflection

**One way the spec helped:** 
The error handling table in `planning.md` included exact quoted agent messages for each failure mode (e.g. `"No listings found for '[description]' under $[max_price]. Try a broader term..."`). Having the precise wording specced out meant the error messages in `run_agent()` and `handle_query()` could be written directly from the table without guessing what to say or what information to include. This also made verifying the no-results branch straightforward — the actual output could be compared word-for-word against the spec.

**One way implementation diverged from the spec:** 
`planning.md` specified that `suggest_outfit` returns a dict with keys `new_item`, `wardrobe`, and `style_notes`, and that `create_fit_card` accepts `outfit (dict)` as its only parameter. The actual scaffold in `tools.py` and `agent.py` defines both functions with string types — `suggest_outfit` returns `str` and `create_fit_card` takes `(outfit: str, new_item: dict)`. The implementation followed the scaffold rather than the planning.md dict design because the scaffold was the authoritative interface that `agent.py`'s session dict and `handle_query()` were already wired to consume. The string interface is also simpler: `outfit_suggestion` is displayed directly in the Gradio panel without any unpacking.

---

## AI Usage

### Instance 1 — Implementing `search_listings`

**What Claude was directed to do:** 
Implement `search_listings()` in `tools.py` using `load_listings()` from the data loader. Claude was given: the Tool 1 block from `planning.md` (the three input parameters with names and types, the full list of return value fields, and the failure mode), the `load_listings()` function signature from `utils/data_loader.py`, and the instruction to filter by price and size, score by keyword overlap with description, drop zero-score listings, and sort highest-score first.

**What was produced:** 
A complete `search_listings` implementation with inclusive price filtering (`<=`), case-insensitive size substring matching, keyword scoring across title, description, category, and style_tags, zero-score removal, and descending sort.

**What was revised before using it:** 
The initial draft used regex word-boundary matching (`\bkeyword\b`) for keyword scoring, which missed multi-word style tags like `"graphic tee"` because the tag is stored as a single string. This was replaced with a `kw in searchable` substring check on the concatenated text of all searchable fields, which correctly scores multi-word keywords. The fix was verified by running `test_search_sorted_by_relevance`, which confirmed that `"Graphic Tee — 2003 Tour Bootleg Style"` ranked first for the query `"vintage graphic tee"`.

---

### Instance 2 — Implementing the planning loop (`run_agent`)

**What Claude was directed to do:** 
Implement `run_agent()` in `agent.py` following the six numbered TODO steps already in the file. Claude was given: the Planning Loop section, State Management section, and ASCII architecture diagram from `planning.md`, along with the pre-filled `_new_session()` dict showing the exact keys to write to at each step. The instruction was to parse the query with regex, guard on empty `search_listings` results, iterate through listings with a `current_index`, and stop on first successful fit card.

**What was produced:** 
A complete `run_agent()` with a `_parse_query()` regex helper, an early-return guard on empty search results, and a `for` loop over listings that catches exceptions from `suggest_outfit` and `create_fit_card` and increments to the next listing on failure.

**What was revised before using it:** 
The generated loop only caught exceptions (`try/except Exception: continue`) but did not handle the case where `create_fit_card` succeeds without raising yet returns an error string (its documented graceful failure mode for an empty outfit). A second guard was added after the call: if the return value starts with `"error:"`, the loop also continues to the next listing. This was verified when the VPN was active — every LLM call returned a 403, all 20 listings were iterated, and `session["error"]` was set with a plain-text summary instead of `fit_card` being silently left as `None`.