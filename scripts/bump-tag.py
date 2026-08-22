#!/usr/bin/env python3
"""Point one service's image tag at a new digest-ish SHA.

    python3 scripts/bump-tag.py einvoice-api 1a2b3c4d5e6f

Called by the build workflow in each service repo, which checks this repo out
and runs it before opening a PR.

Why not `yq -i '.einvoiceApi.image.tag = "..."'`? Because a YAML round-trip
rewrites the whole document: comments are dropped, quoting and key order are
normalised, and the diff becomes hundreds of lines of noise that nobody will
read. values.yaml is mostly commentary explaining *why* each service is pinned
at one replica or why the registry looks the way it does — that is the valuable
part of the file, and a formatter would silently delete it.

So this does a line-level edit instead: find `name: <image>`, then rewrite the
first `tag:` line at the same indentation that follows it. Everything else in
the file is untouched, and the PR diff is exactly one line.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

VALUES = Path(__file__).resolve().parent.parent / "charts" / "plexus" / "values.yaml"

# The image names as they appear in values.yaml under `image.name`. Guards
# against a workflow passing a name that does not exist, which would otherwise
# be a silent no-op: CI stays green, the PR is empty, and the deploy never
# happens.
KNOWN = {"mcp-host-backend", "einvoice-api", "einvoice-mcp", "plexus-frontend"}


def bump(image: str, tag: str) -> str:
    if image not in KNOWN:
        sys.exit(f"unknown image {image!r}; expected one of {sorted(KNOWN)}")
    if not re.fullmatch(r"[0-9a-f]{7,40}", tag):
        # Tags are commit SHAs. Anything else — a branch name, "latest", an
        # empty string from an unset variable — means the caller is broken, and
        # a mutable tag would leave Argo CD reporting Synced while the cluster
        # runs stale code. See the "Never tag latest" note in CLUSTER.md.
        sys.exit(f"tag {tag!r} does not look like a commit SHA")

    lines = VALUES.read_text().splitlines(keepends=True)

    name_re = re.compile(rf"^(\s*)name:\s*{re.escape(image)}\s*$")
    at = next((i for i, ln in enumerate(lines) if name_re.match(ln)), None)
    if at is None:
        sys.exit(f"no `name: {image}` line in {VALUES}")

    indent = name_re.match(lines[at]).group(1)
    tag_re = re.compile(rf"^{indent}tag:\s*(\S+)\s*$")

    # Only look at the handful of lines that belong to this image block. Without
    # a bound, a missing tag: line would march on and hit the *next* service's
    # tag, bumping the wrong image.
    for i in range(at + 1, min(at + 6, len(lines))):
        m = tag_re.match(lines[i])
        if m:
            old = m.group(1)
            if old == tag:
                print(f"{image}: already at {tag}, nothing to do")
                return old
            lines[i] = f"{indent}tag: {tag}\n"
            VALUES.write_text("".join(lines))
            print(f"{image}: {old} -> {tag}")
            return old
        # Dedent means we've left the image block.
        if lines[i].strip() and not lines[i].startswith(indent):
            break

    sys.exit(f"found `name: {image}` but no sibling `tag:` line beneath it")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} <image-name> <commit-sha>")
    bump(sys.argv[1], sys.argv[2])
