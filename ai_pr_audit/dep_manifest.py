"""Dependency manifest parsers for `pyproject.toml` and `requirements.txt`.

The detector (PR #6) compares each extracted import against this manifest. We only
need package names — version specifiers, extras, environment markers all get stripped.
Names are normalised per PEP 503 so `PyYAML`, `pyyaml`, and `Py-Yaml` all collapse
to `pyyaml`.
"""

import re
import tomllib
from dataclasses import dataclass

_REQ_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
_NORMALIZE_RE = re.compile(r"[-_.]+")


def normalize_dist_name(name: str) -> str:
    """PEP 503 canonical form: lowercase, runs of `-`/`_`/`.` collapsed to single `-`."""
    return _NORMALIZE_RE.sub("-", name).lower().strip("-")


@dataclass(frozen=True)
class DepManifest:
    """A project's declared dependency surface.

    `project_name` is the package's own distribution name (from `[project] name`),
    normalised. `declared` is the normalised set of every other dist name the project
    pulls in — runtime + every extras group + (when merged) requirements.txt entries.
    """

    project_name: str | None
    declared: frozenset[str]

    def is_declared(self, dist_name: str) -> bool:
        normalized = normalize_dist_name(dist_name)
        return normalized == self.project_name or normalized in self.declared

    def merge(self, other_declared: frozenset[str]) -> "DepManifest":
        return DepManifest(
            project_name=self.project_name,
            declared=self.declared | other_declared,
        )


def _extract_name(spec: str) -> str | None:
    """Pull the bare package name out of a PEP 508 / requirements-style spec line."""
    match = _REQ_NAME_RE.match(spec.strip())
    return match.group(1) if match else None


def parse_pyproject_toml(content: str) -> DepManifest:
    """Build a `DepManifest` from a `pyproject.toml` source string.

    Reads `[project] name`, `[project] dependencies`, and every group under
    `[project.optional-dependencies]`. Unknown / malformed shapes raise the
    underlying TOML or `KeyError` so the caller can decide what to do.
    """
    data = tomllib.loads(content)
    project = data.get("project", {})

    raw_name = project.get("name")
    project_name = normalize_dist_name(raw_name) if raw_name else None

    declared: set[str] = set()
    for spec in project.get("dependencies", []) or []:
        name = _extract_name(spec)
        if name:
            declared.add(normalize_dist_name(name))

    optional = project.get("optional-dependencies", {}) or {}
    for specs in optional.values():
        for spec in specs or []:
            name = _extract_name(spec)
            if name:
                declared.add(normalize_dist_name(name))

    return DepManifest(project_name=project_name, declared=frozenset(declared))


def parse_requirements_txt(content: str) -> frozenset[str]:
    """Return the normalised package names from a `requirements.txt`-style file.

    Skips blank lines, comment lines, and option lines (anything starting with `-`,
    e.g. `-r other.txt`, `-e .`, `--index-url ...`). Version specifiers, extras, and
    environment markers are dropped — only the bare distribution name survives.
    """
    names: set[str] = set()
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = _extract_name(line)
        if name:
            names.add(normalize_dist_name(name))
    return frozenset(names)
