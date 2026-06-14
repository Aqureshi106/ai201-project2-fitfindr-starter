"""
app.py

Gradio interface for FitFindr. Displays five output panels:
  1. Top listing found       — item details + price comparison verdict
  2. Outfit idea             — suggest_outfit result
  3. Your fit card           — create_fit_card caption
  4. Price analysis          — compare_price full assessment
  5. Style context           — trending styles + retry info + profile status
"""

import gradio as gr

from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── query handler ─────────────────────────────────────────────────────────────

def handle_query(
    user_query: str,
    wardrobe_choice: str,
) -> tuple[str, str, str, str, str]:
    """
    Called by Gradio when the user submits a query.

    Returns five strings mapped to the five output panels:
        (listing_text, outfit_suggestion, fit_card, price_analysis, style_context)
    """
    if not user_query or not user_query.strip():
        return "Please enter a search query.", "", "", "", ""

    wardrobe = (
        get_example_wardrobe()
        if wardrobe_choice == "Example wardrobe"
        else get_empty_wardrobe()
    )

    session = run_agent(user_query.strip(), wardrobe)

    if session["error"]:
        return session["error"], "", "", "", ""

    # Panel 1: listing details + inline price verdict
    item = session["selected_item"]
    verdict = ""
    if session["price_comparison"]:
        verdict = f"\n\nPrice verdict: {session['price_comparison']['verdict'].upper()}"
    retry_note = f"\n\n⚠ {session['retry_info']}" if session["retry_info"] else ""
    listing_text = (
        f"Title:     {item['title']}\n"
        f"Price:     ${item['price']:.2f}\n"
        f"Platform:  {item['platform']}\n"
        f"Size:      {item['size']}\n"
        f"Condition: {item['condition']}\n"
        f"Colors:    {', '.join(item.get('colors', []))}\n"
        f"Brand:     {item.get('brand') or 'unknown'}\n"
        f"Tags:      {', '.join(item.get('style_tags', []))}\n\n"
        f"{item['description']}"
        + verdict
        + retry_note
    )

    # Panel 4: full price comparison breakdown
    pc = session["price_comparison"]
    if pc and pc["comparable_count"] > 0:
        price_analysis = (
            f"Verdict: {pc['verdict'].upper()}\n\n"
            f"{pc['assessment']}\n\n"
            f"Comparables found: {pc['comparable_count']} listing(s)\n"
            f"Average comparable price: ${pc['avg_comparable_price']:.2f}\n"
            f"This item vs. average: {pc['price_diff_pct']:+.1f}%"
        )
    elif pc:
        price_analysis = pc["assessment"]
    else:
        price_analysis = "Price analysis unavailable."

    # Panel 5: style context — trends + profile status
    context_parts = []
    if session["trend_info"]:
        ti = session["trend_info"]
        context_parts.append(
            f"Trending styles for {item['category']}:\n"
            + ", ".join(ti["trending_styles"])
            + f"\n\nHot category right now: {ti['hot_category']}"
            + f"\n({ti['data_source']})"
        )
    if session["profile_used"]:
        context_parts.append(
            "Style profile active: outfit suggestion was shaped by your saved "
            "style preferences from past interactions."
        )
    if session["retry_info"]:
        context_parts.append(session["retry_info"])
    style_context = "\n\n---\n\n".join(context_parts) if context_parts else "No additional context."

    return (
        listing_text,
        session["outfit_suggestion"],
        session["fit_card"],
        price_analysis,
        style_context,
    )


# ── interface ─────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "flowy midi skirt under $40",
    "black combat boots size 8",
    "denim jacket size XS under $20",    # triggers retry logic
    "designer ballgown size XXS under $5", # deliberate no-results test
]


def build_interface():
    with gr.Blocks(title="FitFindr") as demo:
        gr.Markdown("""
# FitFindr 🛍️
Find secondhand pieces and get outfit ideas based on your wardrobe.
Describe what you're looking for — include size and price if you want to filter.
        """)

        with gr.Row():
            query_input = gr.Textbox(
                label="What are you looking for?",
                placeholder="e.g. vintage graphic tee under $30, size M",
                lines=2,
                scale=3,
            )
            wardrobe_choice = gr.Radio(
                choices=["Example wardrobe", "Empty wardrobe (new user)"],
                value="Example wardrobe",
                label="Wardrobe",
                scale=1,
            )

        submit_btn = gr.Button("Find it", variant="primary")

        with gr.Row():
            listing_output = gr.Textbox(
                label="🛍️ Top listing found",
                lines=10,
                interactive=False,
            )
            outfit_output = gr.Textbox(
                label="👗 Outfit idea",
                lines=10,
                interactive=False,
            )
            fitcard_output = gr.Textbox(
                label="✨ Your fit card",
                lines=10,
                interactive=False,
            )

        with gr.Row():
            price_output = gr.Textbox(
                label="💰 Price analysis",
                lines=6,
                interactive=False,
            )
            context_output = gr.Textbox(
                label="🔥 Style context",
                lines=6,
                interactive=False,
            )

        gr.Examples(
            examples=[[q, "Example wardrobe"] for q in EXAMPLE_QUERIES],
            inputs=[query_input, wardrobe_choice],
            label="Try these queries",
        )

        outputs = [
            listing_output,
            outfit_output,
            fitcard_output,
            price_output,
            context_output,
        ]

        submit_btn.click(fn=handle_query, inputs=[query_input, wardrobe_choice], outputs=outputs)
        query_input.submit(fn=handle_query, inputs=[query_input, wardrobe_choice], outputs=outputs)

    return demo


if __name__ == "__main__":
    demo = build_interface()
    demo.launch()
