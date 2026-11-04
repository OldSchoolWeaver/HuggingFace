"""Weekly meal plan state and the tools the agent uses to build it.

The LLM is good at choosing recipes; it is bad at arithmetic across 20+ ingredients.
So the agent only *records* recipes here (add_recipe), and plain Python does the
scaling, unit conversion, de-duplication and aisle grouping (build_shopping_list).
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from smolagents.tools import Tool

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MEALS = ["breakfast", "lunch", "dinner", "snack"]

# ---------------------------------------------------------------- units

# unit alias -> (dimension, factor to base unit: grams or millilitres)
_MEASURED = {
    "mass": {
        ("g", "gr", "gram", "grams"): 1.0,
        ("kg", "kilo", "kilos", "kilogram", "kilograms"): 1000.0,
        ("oz", "ounce", "ounces"): 28.35,
        ("lb", "lbs", "pound", "pounds"): 453.6,
    },
    "volume": {
        ("ml", "millilitre", "millilitres", "milliliter", "milliliters"): 1.0,
        ("cl",): 10.0,
        ("dl",): 100.0,
        ("l", "litre", "litres", "liter", "liters"): 1000.0,
        ("tsp", "teaspoon", "teaspoons"): 5.0,
        ("tbsp", "tbs", "tablespoon", "tablespoons"): 15.0,
        ("cup", "cups"): 240.0,
    },
}
UNIT_TABLE: dict[str, tuple[str, float]] = {
    alias: (dim, factor)
    for dim, groups in _MEASURED.items()
    for aliases, factor in groups.items()
    for alias in aliases
}

# Countable units: normalised to a singular display form.
COUNT_UNITS = {
    "": "", "pc": "", "pcs": "", "piece": "", "pieces": "", "whole": "", "unit": "", "units": "",
    "clove": "clove", "cloves": "clove", "can": "can", "cans": "can", "tin": "can", "tins": "can",
    "bunch": "bunch", "bunches": "bunch", "head": "head", "heads": "head",
    "slice": "slice", "slices": "slice", "pack": "pack", "packs": "pack", "package": "pack",
    "jar": "jar", "jars": "jar", "sprig": "sprig", "sprigs": "sprig", "stalk": "stalk",
    "stalks": "stalk", "fillet": "fillet", "fillets": "fillet", "pinch": "pinch", "handful": "handful",
}

_UNICODE_FRACTIONS = {"½": ".5", "¼": ".25", "¾": ".75", "⅓": ".333", "⅔": ".667", "⅛": ".125"}


def parse_quantity(value: Any) -> Optional[float]:
    """'1 1/2', '1/2', '½', 2, '2-3' -> float (ranges take the upper bound)."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    for sym, dec in _UNICODE_FRACTIONS.items():
        text = text.replace(sym, f" {dec}")
    if "-" in text or "–" in text:  # range like 2-3 -> 3
        text = re.split(r"[-–]", text)[-1]
    total = 0.0
    found = False
    for part in text.split():
        try:
            if "/" in part:
                num, den = part.split("/", 1)
                total += float(num) / float(den)
            else:
                total += float(part)
            found = True
        except (ValueError, ZeroDivisionError):
            continue
    return total if found else None


_PREP_WORDS = {
    "fresh", "freshly", "chopped", "diced", "minced", "sliced", "grated", "shredded", "crushed",
    "finely", "roughly", "thinly", "large", "small", "medium", "ripe", "peeled", "boneless",
    "skinless", "to", "taste", "optional", "cooked", "uncooked", "raw", "softened", "melted",
    "beaten", "halved", "quartered", "rinsed", "drained", "ground_",  # 'ground' kept (ground beef)
}
_NO_SINGULAR = ("ss", "us", "is", "ous")  # asparagus, hummus, couscous, swiss...


def normalize_name(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"\(.*?\)", "", name)  # drop parentheticals
    name = name.split(",")[0]  # "onion, chopped" -> "onion"
    words = [w for w in re.findall(r"[a-zà-ÿ'\-]+", name) if w not in _PREP_WORDS and w != "of"]
    if not words:
        return name.strip()
    last = words[-1]
    if last.endswith("ies") and len(last) > 4:
        last = last[:-3] + "y"
    elif last.endswith("oes"):
        last = last[:-2]
    elif last.endswith("s") and len(last) > 3 and not last.endswith(_NO_SINGULAR):
        last = last[:-1]
    words[-1] = last
    return " ".join(words)


_ING_RE = re.compile(r"^\s*([\d\s./½¼¾⅓⅔⅛\-–]+)?\s*([A-Za-z]+\.?)?\s*(.*)$")


def parse_ingredient(item: Any) -> dict:
    """Accepts {'name','quantity','unit'} dicts or free text like '2 cups flour'."""
    if isinstance(item, dict):
        name = str(item.get("name") or item.get("ingredient") or "").strip()
        qty = parse_quantity(item.get("quantity", item.get("amount")))
        unit = str(item.get("unit") or "").strip().lower().rstrip(".")
        return {"name": name, "quantity": qty, "unit": unit}
    text = str(item).strip()
    m = _ING_RE.match(text)
    qty_txt, maybe_unit, rest = (m.group(1), m.group(2), m.group(3)) if m else (None, None, text)
    unit = ""
    if maybe_unit:
        u = maybe_unit.lower().rstrip(".")
        if u in UNIT_TABLE or u in COUNT_UNITS:
            unit = u
        else:
            rest = f"{maybe_unit} {rest}"
    return {"name": rest.strip() or text, "quantity": parse_quantity(qty_txt), "unit": unit}


# ---------------------------------------------------------------- aisles

AISLES: list[tuple[str, tuple[str, ...]]] = [
    ("🥩 Meat & Fish", ("chicken", "beef", "pork", "lamb", "turkey", "bacon", "sausage", "ham", "chorizo",
                       "salmon", "tuna", "cod", "fish", "shrimp", "prawn", "mince", "steak", "anchov")),
    ("🧀 Dairy & Eggs", ("milk", "cheese", "butter", "cream", "yogurt", "yoghurt", "egg", "parmesan",
                        "mozzarella", "feta", "ricotta", "creme")),
    ("🥬 Produce", ("onion", "garlic", "tomato", "potato", "carrot", "pepper", "lettuce", "spinach", "kale",
                   "cucumber", "zucchini", "courgette", "broccoli", "cauliflower", "mushroom", "lemon", "lime",
                   "apple", "banana", "berry", "avocado", "ginger", "celery", "leek", "cabbage", "herb",
                   "parsley", "cilantro", "coriander leaves", "basil", "mint", "scallion", "spring onion",
                   "shallot", "squash", "pumpkin", "eggplant", "aubergine", "corn", "pea", "bean sprout",
                   "asparagus", "chili", "chilli", "orange", "fruit", "salad", "arugula", "rocket", "thyme",
                   "rosemary", "dill", "sweet potato")),
    ("🍞 Bakery", ("bread", "tortilla", "wrap", "pita", "bun", "baguette", "naan", "roll")),
    ("🧂 Spices & Condiments", ("salt", "cumin", "paprika", "oregano", "cinnamon", "turmeric", "curry",
                               "chili powder", "chilli flakes", "spice", "sauce", "vinegar", "mustard",
                               "ketchup", "mayo", "honey", "syrup", "stock", "broth", "bouillon", "seasoning",
                               "nutmeg", "bay leaf", "vanilla", "miso", "pesto", "harissa")),
    ("🥫 Pantry", ("rice", "pasta", "spaghetti", "noodle", "flour", "sugar", "oil", "oat", "lentil",
                  "chickpea", "bean", "quinoa", "couscous", "can", "tomato paste", "coconut milk", "nut",
                  "almond", "seed", "breadcrumb", "cornstarch", "baking", "yeast", "cocoa", "chocolate")),
    ("🧊 Frozen", ("frozen",)),
]
# Things almost everyone already has: listed separately as "check your pantry".
STAPLES = {"salt", "black pepper", "pepper", "salt and pepper", "water", "olive oil", "vegetable oil",
           "oil", "cooking spray", "ice"}


def aisle_for(name: str) -> str:
    first = name.split()[0] if name else ""
    if first == "frozen":
        return "🧊 Frozen"
    if first in ("canned", "tinned", "dried", "jarred"):
        return "🥫 Pantry"
    # Specific multi-word matches first (e.g. "tomato paste" before "tomato", "sweet potato" before "potato").
    best, best_len = "🛒 Other", 0
    for aisle, keys in AISLES:
        for k in keys:
            if k in name and len(k) > best_len:
                best, best_len = aisle, len(k)
    return best


# ---------------------------------------------------------------- state

@dataclass
class Recipe:
    title: str
    servings: Optional[float]
    ingredients: list[dict]
    steps: list[str]
    source_url: Optional[str] = None
    prep_minutes: Optional[int] = None


@dataclass
class MealPlan:
    people: int = 2
    notes: str = ""
    slots: dict[tuple[str, str], Recipe] = field(default_factory=dict)

    def scale(self, recipe: Recipe) -> float:
        return self.people / recipe.servings if recipe.servings else 1.0

    def ordered(self):
        key = lambda s: (DAYS.index(s[0]) if s[0] in DAYS else 99, MEALS.index(s[1]) if s[1] in MEALS else 99)
        return [(slot, self.slots[slot]) for slot in sorted(self.slots, key=key)]


def _norm_day(day: str) -> str:
    d = str(day).strip().lower()
    for full in DAYS:
        if full.lower().startswith(d[:3]):
            return full
    raise ValueError(f"Unknown day '{day}'. Use one of {DAYS}.")


def _norm_meal(meal: str) -> str:
    m = str(meal).strip().lower()
    if m not in MEALS:
        raise ValueError(f"Unknown meal '{meal}'. Use one of {MEALS}.")
    return m


_STEP_NUM = re.compile(r"^\s*\d+[.)]\s*")  # strip "1." the model may already have added


def _fmt_num(x: float) -> str:
    if abs(x - round(x)) < 0.05:
        return str(int(round(x)))
    for frac, sym in ((0.25, "¼"), (0.5, "½"), (0.75, "¾"), (1 / 3, "⅓"), (2 / 3, "⅔")):
        whole = int(x)
        if abs((x - whole) - frac) < 0.04:
            return f"{whole}{sym}" if whole else sym
    return f"{x:.1f}"


def _fmt_amount(qty: Optional[float], unit: str, convert: bool = True) -> str:
    if qty is None:
        return unit or ""
    if not convert and unit in UNIT_TABLE:  # keep the recipe's own unit, just scaled
        return f"{_fmt_num(qty)} {unit}{'s' if unit == 'cup' and qty > 1 else ''}"
    if unit in UNIT_TABLE:
        dim, factor = UNIT_TABLE[unit]
        base = qty * factor
        if dim == "mass":
            return f"{base / 1000:.2f}".rstrip("0").rstrip(".") + " kg" if base >= 1000 else f"{round(base)} g"
        if base >= 1000:
            return f"{base / 1000:.2f}".rstrip("0").rstrip(".") + " l"
        if base < 15:
            return f"{_fmt_num(base / 5)} tsp"
        if base <= 75:
            return f"{_fmt_num(base / 15)} tbsp"
        return f"{round(base / 10) * 10} ml"
    unit = COUNT_UNITS.get(unit, unit)
    if not unit:
        return _fmt_num(qty)
    plural = unit + ("es" if unit.endswith(("ch", "sh")) else "s") if qty > 1 and unit not in ("pinch",) else unit
    return f"{_fmt_num(qty)} {plural}"


# ---------------------------------------------------------------- tools

class StartMealPlanTool(Tool):
    name = "start_meal_plan"
    description = (
        "Starts a NEW, empty weekly meal plan (clears any previous one). Call once at the beginning of a new plan. "
        "Do NOT call it when the user only wants to change an existing plan."
    )
    inputs = {
        "people": {"type": "integer", "description": "How many people to cook for; all recipes are scaled to this."},
        "notes": {"type": "string", "description": "Diet, allergies, budget or other preferences, e.g. 'vegetarian, no nuts'.", "nullable": True},
    }
    output_type = "string"

    def __init__(self, plan: MealPlan, **kwargs):
        super().__init__(**kwargs)
        self.plan = plan

    def forward(self, people: int, notes: Optional[str] = None) -> str:
        self.plan.people = max(1, int(people))
        self.plan.notes = notes or ""
        self.plan.slots.clear()
        return f"New meal plan started for {self.plan.people} people. Notes: {self.plan.notes or 'none'}."


class AddRecipeTool(Tool):
    name = "add_recipe"
    description = (
        "Puts a recipe in a day/meal slot of the weekly plan (replaces whatever was there). "
        "ingredients must be a list of dicts like {'name': 'chicken thigh', 'quantity': 500, 'unit': 'g'} "
        "- name is only the ingredient (no prep words), unit is one of g, kg, ml, l, tsp, tbsp, cup, clove, can, "
        "bunch or '' for counted items (e.g. {'name': 'onion', 'quantity': 2, 'unit': ''}). "
        "Quantities are for the recipe as written; the plan scales them to the household size."
    )
    inputs = {
        "day": {"type": "string", "description": "Day of the week, e.g. 'Monday'."},
        "meal": {"type": "string", "description": "One of 'breakfast', 'lunch', 'dinner', 'snack'."},
        "title": {"type": "string", "description": "Recipe name."},
        "servings": {"type": "integer", "description": "How many servings the recipe makes as written."},
        "ingredients": {"type": "array", "description": "List of ingredient dicts {name, quantity, unit}."},
        "steps": {"type": "array", "description": "List of short cooking-step strings, in order."},
        "source_url": {"type": "string", "description": "URL where the recipe came from, if any.", "nullable": True},
        "prep_minutes": {"type": "integer", "description": "Total time in minutes, if known.", "nullable": True},
    }
    output_type = "string"

    def __init__(self, plan: MealPlan, **kwargs):
        super().__init__(**kwargs)
        self.plan = plan

    def forward(self, day, meal, title, servings, ingredients, steps, source_url=None, prep_minutes=None) -> str:
        day, meal = _norm_day(day), _norm_meal(meal)
        parsed = [parse_ingredient(i) for i in (ingredients or [])]
        parsed = [p for p in parsed if p["name"]]
        if not parsed:
            raise ValueError("A recipe needs at least one ingredient.")
        if isinstance(steps, str):
            steps = [s.strip() for s in re.split(r"\n+|(?<=\.)\s+(?=\d+\.)", steps) if s.strip()]
        self.plan.slots[(day, meal)] = Recipe(
            title=title, servings=parse_quantity(servings), ingredients=parsed,
            steps=[str(s) for s in (steps or [])], source_url=source_url,
            prep_minutes=int(prep_minutes) if prep_minutes else None,
        )
        return f"Added '{title}' to {day} {meal} ({len(parsed)} ingredients). Plan now has {len(self.plan.slots)} meals."


class RemoveRecipeTool(Tool):
    name = "remove_recipe"
    description = "Removes the recipe in a day/meal slot of the current plan."
    inputs = {
        "day": {"type": "string", "description": "Day of the week."},
        "meal": {"type": "string", "description": "One of 'breakfast', 'lunch', 'dinner', 'snack'."},
    }
    output_type = "string"

    def __init__(self, plan: MealPlan, **kwargs):
        super().__init__(**kwargs)
        self.plan = plan

    def forward(self, day: str, meal: str) -> str:
        removed = self.plan.slots.pop((_norm_day(day), _norm_meal(meal)), None)
        return f"Removed '{removed.title}'." if removed else "That slot was already empty."


class ViewMealPlanTool(Tool):
    name = "view_meal_plan"
    description = "Returns the current weekly plan as markdown: an overview table plus every recipe scaled to the household, with steps."
    inputs = {}
    output_type = "string"

    def __init__(self, plan: MealPlan, **kwargs):
        super().__init__(**kwargs)
        self.plan = plan

    def forward(self) -> str:
        p = self.plan
        if not p.slots:
            return "The meal plan is empty."
        out = [f"# 🗓️ Weekly meal plan — {p.people} people" + (f" ({p.notes})" if p.notes else ""), "",
               "| Day | Meal | Recipe | Time |", "|---|---|---|---|"]
        for (day, meal), r in p.ordered():
            out.append(f"| {day} | {meal.title()} | {r.title} | {f'{r.prep_minutes} min' if r.prep_minutes else '–'} |")
        out.append("\n# 👩‍🍳 Recipes")
        for (day, meal), r in p.ordered():
            k = p.scale(r)
            out.append(f"\n## {day} {meal} — {r.title}")
            if r.source_url:
                out.append(f"Source: {r.source_url}")
            out.append(f"_Serves {p.people}" + (f" (scaled ×{k:.2g} from {_fmt_num(r.servings)})" if abs(k - 1) > 0.01 else "") + "_\n")
            for i in r.ingredients:
                qty = i["quantity"] * k if i["quantity"] is not None else None
                amount = _fmt_amount(qty, i["unit"], convert=False)
                out.append(f"- {amount + ' ' if amount else ''}{i['name']}")
            if r.steps:
                out.append("")
                out += [f"{n}. {_STEP_NUM.sub('', s)}" for n, s in enumerate(r.steps, 1)]
        return "\n".join(out)


class BuildShoppingListTool(Tool):
    name = "build_shopping_list"
    description = (
        "Builds the consolidated shopping list for the whole plan: scales every recipe to the household, "
        "converts and sums units, merges duplicates and groups items by supermarket aisle. Returns markdown."
    )
    inputs = {}
    output_type = "string"

    def __init__(self, plan: MealPlan, **kwargs):
        super().__init__(**kwargs)
        self.plan = plan

    def forward(self) -> str:
        p = self.plan
        if not p.slots:
            return "The meal plan is empty - add recipes first."
        # key: (normalized name, dimension or count-unit) -> totals
        totals: dict[tuple[str, str], dict] = {}
        for (day, _meal), r in p.ordered():
            k = p.scale(r)
            for i in r.ingredients:
                name = normalize_name(i["name"])
                unit = i["unit"]
                if unit in UNIT_TABLE:
                    dim, factor = UNIT_TABLE[unit]
                    key, qty, disp_unit = (name, dim), (i["quantity"] * factor * k if i["quantity"] is not None else None), ("g" if dim == "mass" else "ml")
                else:
                    cu = COUNT_UNITS.get(unit, unit)
                    key, qty, disp_unit = (name, f"count:{cu}"), (i["quantity"] * k if i["quantity"] is not None else None), cu
                entry = totals.setdefault(key, {"name": name, "qty": 0.0, "unit": disp_unit, "unknown": False, "days": []})
                if qty is None:
                    entry["unknown"] = True
                else:
                    entry["qty"] += qty
                if day[:3] not in entry["days"]:
                    entry["days"].append(day[:3])

        by_aisle: dict[str, list[str]] = defaultdict(list)
        staples: list[str] = []
        for e in sorted(totals.values(), key=lambda e: e["name"]):
            if e["name"] in STAPLES:
                staples.append(e["name"])
                continue
            qty = e["qty"]
            if qty and e["unit"] not in ("g", "ml", "pinch", "handful"):
                qty = math.ceil(qty - 1e-6)  # you can't buy 1.5 onions
            amount = _fmt_amount(qty, e["unit"]) if qty else ""
            if e["unknown"]:
                amount = (amount + " + some").strip() if amount else "some"
            by_aisle[aisle_for(e["name"])].append(f"- [ ] **{e['name']}** — {amount}  _({', '.join(e['days'])})_")

        order = [a for a, _ in AISLES] + ["🛒 Other"]
        out = [f"# 🛒 Shopping list — {len(p.slots)} meals, {p.people} people", ""]
        for aisle in order:
            if by_aisle.get(aisle):
                out += [f"### {aisle}", *by_aisle[aisle], ""]
        if staples:
            out.append("**Check your pantry:** " + ", ".join(sorted(set(staples))))
        return "\n".join(out)


def meal_plan_tools(plan: Optional[MealPlan] = None) -> list[Tool]:
    plan = plan or MealPlan()
    return [StartMealPlanTool(plan), AddRecipeTool(plan), RemoveRecipeTool(plan),
            ViewMealPlanTool(plan), BuildShoppingListTool(plan)]
