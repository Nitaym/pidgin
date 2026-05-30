from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pidgin.recipes.models import RoleRecipe


def canonical_bundle_json(recipe: RoleRecipe) -> str:
    data = recipe.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def bundle_sha256(recipe: RoleRecipe) -> str:
    return hashlib.sha256(canonical_bundle_json(recipe).encode("utf-8")).hexdigest()


def load_role_recipe(path: Path) -> RoleRecipe:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return RoleRecipe.model_validate(raw)


def load_role_recipe_from_url(source_url: str) -> RoleRecipe:
    if source_url.startswith("file://"):
        path = Path(source_url.removeprefix("file://"))
    else:
        path = Path(source_url)
    return load_role_recipe(path)
