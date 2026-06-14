# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
search_listing will look into the listings.json file and find the item of which the user desires to purchase, along with the size if given by the user, and the maximum price limit of which the user is willing to pay for the item. What will be given are the matching listings of the desired item.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `description` (str): Representing the desired item of the user
- `size` (str): Representing the size described by the user.
- `max_price` (float): Representing the maximum price limit that the user is willing to pay for the item.

**What it returns:**
<!-- Describe the return value — what fields does a result contain? --> What will be returned would be a list of dictionaries where each dictionary represents one matching listing, being the id, title, description, category, style-tags, size, condition, price, colors, brand, and platform as the keys which bear values.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if no listings match? -->
If the tool fails or returns nothing, the agent should ask the user to broaden the description or raise the price limit, then stop. The agent should not call suggest_outfit due to the empty input.
---

### Tool 2: suggest_outfit

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
suggest_outfit takes the output of the desired item of the user from search_listings along with the wardrobe of what the user commonly wears and it will find a complete outfit pairing for the user which combines the desired item with what the user usually wears.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): Representing the desired item of the user from search_listings of which the dictionary bears the id, title, description, category, style-tags, size, condition, price, colors, brand, and platform. 
- `wardrobe` (dict): Representing what the user commonly wears of which the dictionary would conform to what is prescribed in the wardrobe_schema.json file.

**What it returns:**
<!-- Describe the return value -->
what will be returned is the complete outfit pairing in the form of a dictionary containing the desired item, the commonly worn items of the user, and the style_notes as keys and the value reprsenting what they are. The style_notes are how the user should fashion themselves with their items.

**What happens if it fails or returns nothing:**
<!-- What should the agent do if the wardrobe is empty or no outfit can be suggested? -->
If suggest_outfit fails or returns nothing, the agent should call suggest_outfit with a generic wardrobe so it could produce a pairing, then inform the user that the suggestion is general as no wardrobe was provided. If no outfit can be formed with the output of search_listing and the commonly worn items of the user, the agent should skip the create_fit_card for the desired item and try the next listing from the output of search_listing or return just the listing info to the user with a message such as "Found this item but couldn't generate a styling suggestion."

---

### Tool 3: create_fit_card

**What it does:**
<!-- Describe what this tool does in 1–2 sentences -->
create_fit_card will take in the outfit object which is the dictionary from the output of suggest_outfit which will produce a structured card showing the item, the price, and how to style it.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `outfit` (dict): Representing the output of suggest_outfit being a dictionary bearing the desired item, the commonly worn items of the user, and the style notes as keys and the values representing what they are.

**What it returns:**
<!-- Describe the return value -->
What will be returned is a dictionary representing the rendered fit card with the following keys: `card_id` (a unique identifier for the card), `item` (the listing dict from search_listings containing title, price, platform, and image_url), `outfit` (the wardrobe pieces dict from suggest_outfit), `style_notes` (the styling advice string), and `tags` (a list of style tags derived from the item).


**What happens if it fails or returns nothing:**
<!-- What should the agent do if the outfit data is incomplete? -->
If create_fit_card fails or returns nothing, the agent should skip rendering that card and return something useful to the user. If the outfit data is incomplete, the agent should log the failure, skip the card, and if other listings exist from step 1, it will attempt to build a card for the next one instead. If all cards fail, the agent should fall back to the returning a plain-text summary to the user.

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**
<!-- Describe the logic your planning loop uses. What does it look at? What conditions change its behavior? How does it know when it's done? -->
The agent parses the user query to extract a description, max_price, and size (if provided), then calls search_listings. If no description or max_price can be extracted, it asks the user to clarify before proceeding. If search_listings returns results, the agent selects the first (closest-matching) listing and calls suggest_outfit, using the user's stated wardrobe or a generic fallback if none was provided. For each outfit returned, the agent calls create_fit_card. If create_fit_card fails for the current listing, the agent increments to the next listing in the results and retries suggest_outfit and create_fit_card. The agent is done when at least one fit card is successfully created and returned, or when all listings have been exhausted, at which point it provides a plain-text summary.

---

## State Management

**How does information from one tool get passed to the next?**
<!-- Describe how your agent stores and accesses state within a session. What data is tracked? How is it passed between tool calls? -->
The agent tracks the following state variables across tool calls within a session:
- `listings` (list): the full list of dicts returned by search_listings, kept so the agent can iterate through remaining options on failure.
- `current_index` (int): the index into `listings` indicating which listing is currently being processed. Incremented when suggest_outfit or create_fit_card fails for that listing.
- `outfit` (dict): the dict returned by suggest_outfit for the current listing, passed directly as input to create_fit_card.
- `fit_cards` (list): the list of successfully created fit card dicts returned by create_fit_card, accumulated until the agent is done.

Each tool receives its inputs from the state variables above rather than from the raw user query, ensuring that data flows cleanly from one tool to the next without re-parsing.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Reply: "No listings found for '[description]' under $[max_price]. Try a broader term (e.g. 'graphic tee' instead of 'vintage graphic tee') or raise your price limit." Then stop — do not call suggest_outfit. |
| suggest_outfit | Wardrobe is empty or not provided | Retry suggest_outfit with a generic wardrobe ({"style": "casual"}), then reply: "I couldn't find a wardrobe in your message, so I styled this with a general casual look. Tell me what you usually wear for a more tailored suggestion." |
| create_fit_card | Outfit input is missing or incomplete | Log the failure internally, skip that card, and try the next listing. If all listings fail, reply: "I found [n] listing(s) for '[description]' but couldn't build a fit card. Here's what was available: [listing title, price, platform per line]." |

---

## Architecture

```
User query: "I'm looking for a vintage graphic tee under $30.
             I mostly wear baggy jeans and chunky sneakers."
    │
    ▼
Planning Loop
    │  Parses: description="vintage graphic tee", max_price=30.0, size=None
    │  Parses: wardrobe={"bottoms": "baggy jeans", "shoes": "chunky sneakers"}
    │  Initializes: listings=[], current_index=0, outfit=None, fit_cards=[]
    │
    ├─► search_listings(description, size, max_price)
    │       │
    │       ├── results=[]
    │       │       └─► [ERROR] Ask user to broaden description or raise price limit → STOP
    │       │
    │       └── results=[item, ...]
    │               │
    │               ▼
    │           Session: listings=results, current_index=0
    │               │
    ├─► suggest_outfit(new_item=listings[current_index], wardrobe)
    │       │
    │       ├── wardrobe empty / not provided
    │       │       └─► retry suggest_outfit with generic wardrobe
    │       │               │  Inform user: "Suggestion is general — no wardrobe provided"
    │       │               ▼
    │       │
    │       ├── no outfit can be formed
    │       │       └─► current_index += 1
    │       │               ├── more listings remain → loop back to suggest_outfit
    │       │               └── no listings remain → return listing info + "couldn't generate styling suggestion" → STOP
    │       │
    │       └── outfit={new_item, wardrobe_pieces, style_notes}
    │               │
    │               ▼
    │           Session: outfit=result
    │               │
    ├─► create_fit_card(outfit)
    │       │
    │       ├── outfit incomplete / tool fails
    │       │       └─► log failure, current_index += 1
    │       │               ├── more listings remain → loop back to suggest_outfit
    │       │               └── no listings remain → return plain-text summary of all found listings → STOP
    │       │
    │       └── fit_card={card_id, item, outfit, style_notes, tags}
    │               │
    │               ▼
    │           Session: fit_cards.append(fit_card)
    │               │
    │               ├── more listings remain → current_index += 1 → loop back to suggest_outfit
    │               └── all listings processed → DONE
    │
    ▼
Return fit_cards to user (one card per successfully styled listing)
```

---

## AI Tool Plan

<!-- For each part of the implementation below, describe:
     - Which AI tool you plan to use (Claude, Copilot, ChatGPT, etc.)
     - What you'll give it as input (which sections of this planning.md, your agent diagram)
     - What you expect it to produce
     - How you'll verify the output matches your spec before moving on

     "I'll use AI to help me code" is not a plan.
     "I'll give Claude my Tool 1 spec (inputs, return value, failure mode) and ask it to implement
     search_listings() using load_listings() from the data loader — then test it against 3 queries
     before trusting it" is a plan. -->

**Milestone 3 — Individual tool implementations:**

For `search_listings`: I'll give Claude the Tool 1 block from planning.md (what it does, input parameters, return value, failure mode) and ask it to implement `search_listings()` using `load_listings()` from the data loader. I'll check that the generated code filters by description, size (skipped when None), and max_price, and that it returns the correct keys (id, title, description, category, style_tags, size, condition, price, colors, brand, platform). I'll verify by running 3 test queries: one with all three parameters, one with size=None, and one that should return no results to confirm the empty-results message fires.

For `suggest_outfit`: I'll give Claude the Tool 2 block from planning.md (inputs, return value, both failure modes) and ask it to implement `suggest_outfit()`. I'll check that the generated code handles the empty-wardrobe case by substituting a generic wardrobe and that the returned dict contains new_item, wardrobe, and style_notes keys. I'll verify with two tests: one where wardrobe is provided normally, and one where wardrobe is an empty dict to confirm the generic fallback and user message both appear.

For `create_fit_card`: I'll give Claude the Tool 3 block from planning.md (input, return value with all five keys, failure mode) and ask it to implement `create_fit_card()`. I'll check that the returned dict contains card_id, item, outfit, style_notes, and tags, and that passing an incomplete outfit dict triggers the failure path. I'll verify by passing a valid outfit dict and confirming all five keys are present, then passing a dict missing style_notes and confirming the failure is handled.

**Milestone 4 — Planning loop and state management:**

I'll give Claude the Planning Loop section, the State Management section, and the Architecture diagram from planning.md and ask it to implement the planning loop that manages current_index, listings, outfit, and fit_cards across tool calls. I'll check that the generated code initializes all four state variables, increments current_index on failure, and terminates correctly when fit_cards is non-empty or all listings are exhausted. I'll verify with three end-to-end runs: the happy path using the example query from the Complete Interaction section, a run where suggest_outfit fails on the first listing and succeeds on the second (confirming current_index increments), and a run where all listings fail (confirming the plain-text summary is returned instead of an empty fit_cards list).

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
<!-- What does the agent do first? Which tool is called? With what input? --> 
The agent parses the query and calls search_listings(description="vintage graphic tee", size=None, max_price=30.0). The tool returns a list of matching listing dicts, for example: [{"id": "L042", "title": "Vintage Grateful Dead Tee", "description": "Faded band tee, great condition", "category": "tops", "style_tags": ["vintage", "graphic", "oversized"], "size": "M", "condition": "good", "price": 24.0, "colors": ["black"], "brand": "unknown", "platform": "Depop"}, ...]. Session state is updated: listings=results, current_index=0.

**Step 2:**
<!-- What happens next? What was returned from step 1? What tool is called now? --> 
The agent selects the first listing from the results of step 1 (listings[0]) and calls suggest_outfit with new_item being that listing dict and wardrobe being {"bottoms": "baggy jeans", "shoes": "chunky sneakers"} as extracted from the user query. The tool returns a dict such as {"new_item": {...}, "wardrobe": {"bottoms": "baggy jeans", "shoes": "chunky sneakers"}, "style_notes": "Tuck the front of the tee, cuff the jeans once, and let the chunky sneakers anchor the look."}.

**Step 3:**
<!-- Continue until the full interaction is complete -->
The agent calls create_fit_card with the outfit dict returned from step 2. The tool returns a structured fit card dict with keys card_id, item, outfit, style_notes, and tags — representing the first visual fit card showing the item, price, and how to style it.

**Final output to user:**
<!-- What does the user actually see at the end? -->
The user sees one or more fit cards rendered in the Gradio UI. Each card displays the listing title ("Vintage Grateful Dead Tee"), price ($24.00), platform (Depop), the outfit pairing (baggy jeans, chunky sneakers), and the style notes ("Tuck the front of the tee, cuff the jeans once, and let the chunky sneakers anchor the look."). This directly answers both questions from the original query: what listings are available and how to style them.