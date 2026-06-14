from pidgin.hire.seed import (
    SeedAgent,
    load_seed_manifest,
    seed_workspace_agents,
)
from pidgin.hire.service import (
    HR_RECIPE_ID,
    HireError,
    HireRequest,
    TemplateHireRequest,
    derive_handle,
    get_hr_agent,
    hire_from_recipe,
    hire_support_agent,
    hire_with_template,
)

__all__ = [
    "HR_RECIPE_ID",
    "HireError",
    "HireRequest",
    "SeedAgent",
    "TemplateHireRequest",
    "derive_handle",
    "get_hr_agent",
    "hire_from_recipe",
    "hire_support_agent",
    "hire_with_template",
    "load_seed_manifest",
    "seed_workspace_agents",
]
