from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pidgin.types.customization import HireCustomization
from pidgin.util.ids import utc_now_iso
from pidgin.util.slug import slugify

_SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class TemplateError(Exception):
    pass


@dataclass
class TemplateManifest:
    name: str
    slug: str
    current_version: int
    created_at: str
    updated_at: str
    lineage: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "slug": self.slug,
            "current_version": self.current_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.lineage:
            data["lineage"] = self.lineage
        return data


def _templates_root(workspace_root: Path) -> Path:
    return workspace_root / "role-templates"


def _slug_dir(workspace_root: Path, slug: str) -> Path:
    return _templates_root(workspace_root) / slug


def _manifest_path(workspace_root: Path, slug: str) -> Path:
    return _slug_dir(workspace_root, slug) / "manifest.json"


def _version_path(workspace_root: Path, slug: str, version: int) -> Path:
    return _slug_dir(workspace_root, slug) / f"v{version}.md"


def _parse_simple_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    frontmatter: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip()
    body = text[match.end() :]
    return frontmatter, body


def _section(body: str, heading: str) -> str:
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(body)
    return match.group(1).strip() if match else ""


def _subsection(section: str, heading: str) -> str:
    pattern = re.compile(
        rf"^### {re.escape(heading)}\s*\n(.*?)(?=^### |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(section)
    return match.group(1).strip() if match else ""


def _bullet_list(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def parse_version_body(text: str) -> HireCustomization:
    from pidgin.types.customization import IdealCandidate, JobRequirements

    _, body = _parse_simple_frontmatter(text)
    job_section = _section(body, "Job requirements")
    ideal_section = _section(body, "Ideal candidate profile")
    your_take = _section(body, "Your take")
    return HireCustomization(
        job_requirements=JobRequirements(
            mission=_subsection(job_section, "Mission"),
            responsibilities=_bullet_list(_subsection(job_section, "Responsibilities")),
            out_of_scope=_bullet_list(_subsection(job_section, "Out of scope")),
        ),
        ideal_candidate=IdealCandidate(
            tone=_subsection(ideal_section, "Tone"),
            decision_framework=_subsection(ideal_section, "Decision framework"),
            escalation_rules=_subsection(ideal_section, "Escalation rules"),
        ),
        your_take=your_take,
    )


def render_version_body(
    customization: HireCustomization,
    *,
    version: int,
    created_at: str,
    created_by_principal_id: str,
) -> str:
    job = customization.job_requirements
    ideal = customization.ideal_candidate
    lines = [
        "---",
        f"version: {version}",
        f"created_at: {created_at}",
        f"created_by_principal_id: {created_by_principal_id}",
        "---",
        "",
        "## Job requirements",
        "",
        "### Mission",
        job.mission or "",
        "",
        "### Responsibilities",
    ]
    lines.extend(f"- {item}" for item in job.responsibilities)
    lines.extend(["", "### Out of scope"])
    lines.extend(f"- {item}" for item in job.out_of_scope)
    lines.extend(
        [
            "",
            "## Ideal candidate profile",
            "",
            "### Tone",
            ideal.tone or "",
            "",
            "### Decision framework",
            ideal.decision_framework or "",
            "",
            "### Escalation rules",
            ideal.escalation_rules or "",
            "",
            "## Your take",
            customization.your_take or "",
            "",
        ]
    )
    return "\n".join(lines)


def _read_manifest(workspace_root: Path, slug: str) -> TemplateManifest:
    path = _manifest_path(workspace_root, slug)
    if not path.is_file():
        raise TemplateError(f"Template not found: {slug}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return TemplateManifest(
        name=data["name"],
        slug=data["slug"],
        current_version=int(data["current_version"]),
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        lineage=data.get("lineage"),
    )


def _write_manifest(workspace_root: Path, manifest: TemplateManifest) -> None:
    path = _manifest_path(workspace_root, manifest.slug)
    path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")


def resolve_template_slug(name: str, slug: str | None = None) -> str:
    candidate = slug or slugify(name)
    if not _SLUG_PATTERN.match(candidate):
        raise TemplateError("Template slug must be kebab-case")
    return candidate


def list_workspace_template_summaries(workspace_root: Path) -> list[dict[str, Any]]:
    templates_dir = _templates_root(workspace_root)
    if not templates_dir.is_dir():
        return []

    summaries: list[dict[str, Any]] = []
    for slug_dir in sorted(templates_dir.iterdir()):
        if not slug_dir.is_dir():
            continue
        try:
            manifest = _read_manifest(workspace_root, slug_dir.name)
        except TemplateError:
            continue
        summaries.append(
            {
                "source": "workspace",
                "slug": manifest.slug,
                "name": manifest.name,
                "current_version": manifest.current_version,
                "updated_at": manifest.updated_at,
            }
        )
    return summaries


def get_workspace_template(
    workspace_root: Path,
    slug: str,
    *,
    version: int | None = None,
) -> dict[str, Any]:
    manifest = _read_manifest(workspace_root, slug)
    version_num = version or manifest.current_version
    version_path = _version_path(workspace_root, slug, version_num)
    if not version_path.is_file():
        raise TemplateError(f"Version {version_num} not found for template {slug}")
    body_text = version_path.read_text(encoding="utf-8")
    customization = parse_version_body(body_text)
    return {
        "source": "workspace",
        "slug": manifest.slug,
        "name": manifest.name,
        "version": version_num,
        "current_version": manifest.current_version,
        "updated_at": manifest.updated_at,
        "lineage": manifest.lineage,
        "customization": customization.model_dump(),
        "body_markdown": body_text,
    }


def create_workspace_template(
    workspace_root: Path,
    *,
    name: str,
    slug: str | None,
    customization: HireCustomization,
    actor_principal_id: str,
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_slug = resolve_template_slug(name, slug)
    slug_dir = _slug_dir(workspace_root, resolved_slug)
    if slug_dir.exists():
        raise TemplateError(f"Template slug already exists: {resolved_slug}")

    now = utc_now_iso()
    slug_dir.mkdir(parents=True, exist_ok=False)
    manifest = TemplateManifest(
        name=name,
        slug=resolved_slug,
        current_version=1,
        created_at=now,
        updated_at=now,
        lineage=lineage,
    )
    _write_manifest(workspace_root, manifest)
    body = render_version_body(
        customization,
        version=1,
        created_at=now,
        created_by_principal_id=actor_principal_id,
    )
    _version_path(workspace_root, resolved_slug, 1).write_text(body, encoding="utf-8")
    from pidgin.audit.template_versions import append_template_version_audit

    append_template_version_audit(
        workspace_root,
        slug=resolved_slug,
        actor_principal_id=actor_principal_id,
        from_version=None,
        to_version=1,
        summary=f"Created template {name}",
    )
    return get_workspace_template(workspace_root, resolved_slug)


def save_workspace_template_version(
    workspace_root: Path,
    slug: str,
    *,
    name: str | None,
    customization: HireCustomization,
    actor_principal_id: str,
) -> dict[str, Any]:
    manifest = _read_manifest(workspace_root, slug)
    from_version = manifest.current_version
    to_version = from_version + 1
    now = utc_now_iso()
    if name:
        manifest.name = name
    manifest.current_version = to_version
    manifest.updated_at = now
    _write_manifest(workspace_root, manifest)
    body = render_version_body(
        customization,
        version=to_version,
        created_at=now,
        created_by_principal_id=actor_principal_id,
    )
    _version_path(workspace_root, slug, to_version).write_text(body, encoding="utf-8")
    from pidgin.audit.template_versions import append_template_version_audit

    append_template_version_audit(
        workspace_root,
        slug=slug,
        actor_principal_id=actor_principal_id,
        from_version=from_version,
        to_version=to_version,
        summary=f"Saved template {manifest.name} v{to_version}",
    )
    return get_workspace_template(workspace_root, slug)


def delete_workspace_template(workspace_root: Path, slug: str) -> None:
    slug_dir = _slug_dir(workspace_root, slug)
    if not slug_dir.is_dir():
        raise TemplateError(f"Template not found: {slug}")
    shutil.rmtree(slug_dir)


def customization_from_template(
    workspace_root: Path,
    slug: str,
    *,
    version: int | None = None,
) -> HireCustomization:
    detail = get_workspace_template(workspace_root, slug, version=version)
    return HireCustomization.model_validate(detail["customization"])
