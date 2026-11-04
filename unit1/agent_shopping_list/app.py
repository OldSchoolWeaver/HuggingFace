"""Weekly meal planner + shopping list agent (smolagents CodeAgent + Gradio).

The LLM finds and picks recipes; deterministic tools in tools/meal_plan.py keep the
plan, scale it to the household and build the consolidated shopping list.
"""
import os

from smolagents import CodeAgent, DuckDuckGoSearchTool, InferenceClientModel

from Gradio_UI import GradioUI
from tools.meal_plan import MealPlan, meal_plan_tools
from tools.visit_webpage import VisitWebpageTool

# Change the model without touching code: set MODEL_ID / HF_PROVIDER as Space variables.
# The model must be served by an Inference Provider you have enabled (see the model page's
# "Inference Providers" panel and https://huggingface.co/settings/inference-providers).
# HF_TOKEN (Space secret) is picked up automatically.
model = InferenceClientModel(
    model_id=os.getenv("MODEL_ID", "Qwen/Qwen3-Coder-480B-A35B-Instruct"),
    provider=os.getenv("HF_PROVIDER") or None,
    max_tokens=4096,  # a full week of recipes needs room
    temperature=0.4,
)

MEAL_PLANNER_INSTRUCTIONS = """
You are a weekly meal planner. You plan a week of meals and produce a consolidated shopping list using the
tools start_meal_plan, add_recipe, remove_recipe, view_meal_plan, build_shopping_list, web_search and visit_webpage.

Workflow for a NEW plan:
1. Work out the requirements. When the user does not say, assume: 7 days (Monday to Sunday), dinner only,
   2 people, no dietary restrictions. Respect every diet, allergy, budget, cuisine or time constraint given.
2. Call start_meal_plan(people=..., notes=...) exactly once.
3. Choose a varied week: rotate proteins and cuisines, no repeated dish, and reuse fresh ingredients across
   days (e.g. half a bunch of coriander on Monday, the rest on Thursday) to cut waste and cost.
4. Find real recipes efficiently: run several web_search calls inside ONE code block with a for loop and print
   short results. Only use visit_webpage when you need exact quantities, and at most 3 times in total;
   print only the ingredients/method part of a page, never the whole page. If searching or a page fails,
   write a sound recipe from your own cooking knowledge instead of retrying - that is fine.
5. Call add_recipe once per meal. ingredients is a list of dicts, e.g.
   [dict(name="chicken thigh", quantity=500, unit="g"), dict(name="onion", quantity=2, unit="")]
   Name = the bare ingredient (no "chopped", "fresh"...). Use metric units where you can.
   Give quantities for the recipe as written plus its servings: the tool scales to the household itself.
   Add several recipes in the same code block to save steps.
6. Finish with exactly:
   plan = view_meal_plan()
   shopping = build_shopping_list()
   final_answer(plan + "\\n\\n" + shopping)

Changing an EXISTING plan (e.g. "swap Wednesday for something vegetarian", "add lunches"):
do NOT call start_meal_plan; use add_recipe (it replaces a slot) or remove_recipe, then finish with step 6.

Never do the shopping-list maths yourself - build_shopping_list does the scaling, unit conversion and merging.
"""

plan = MealPlan()

agent = CodeAgent(
    model=model,
    tools=[
        DuckDuckGoSearchTool(max_results=5),
        VisitWebpageTool(),
        *meal_plan_tools(plan),
    ],  # final_answer is added automatically
    instructions=MEAL_PLANNER_INSTRUCTIONS,
    max_steps=15,
    verbosity_level=1,
)

if __name__ == "__main__":
    GradioUI(
        agent,
        title="🛒 Weekly Meal Planner",
        description=(
            "Tell me who you're cooking for and any preferences. I'll plan the week's meals with recipes "
            "and build one shopping list grouped by aisle. Ask follow-ups to swap meals and I'll update the list."
        ),
        examples=[
            "Plan dinners for this week for 2 people",
            "Vegetarian dinners Monday to Friday for a family of 4, kids don't like spicy food",
            "Mediterranean lunches and dinners for 7 days, 2 people, under 30 minutes each",
            "High-protein dinners for 1 person, no pork, use leftovers for lunch the next day",
        ],
    ).launch()
