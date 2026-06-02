from __future__ import annotations

from urllib.parse import parse_qs

from pidgin.connectors.types import ResourceUri


class ResourceUriError(ValueError):
    pass


def parse_resource_uri(raw: str) -> ResourceUri:
    if ":" not in raw:
        raise ResourceUriError(f"Invalid resource URI (missing prefix): {raw}")

    prefix, rest = raw.split(":", 1)
    if "/" not in rest:
        raise ResourceUriError(f"Invalid resource URI (missing kind/id): {raw}")

    kind, id_part = rest.split("/", 1)
    if "?" in id_part:
        resource_id, query_string = id_part.split("?", 1)
        parsed = parse_qs(query_string, keep_blank_values=True)
        query = {k: v[0] if v else "" for k, v in parsed.items()}
    else:
        resource_id = id_part
        query = {}

    if not prefix or not kind or not resource_id:
        raise ResourceUriError(f"Invalid resource URI: {raw}")

    return ResourceUri(prefix=prefix, kind=kind, resource_id=resource_id, query=query)
