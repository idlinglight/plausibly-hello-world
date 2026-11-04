# Workflows

Each workflow keeps a one-line header and comments about its own lines
only. Everything else about it, the why, dates, observations, vendor
behaviour, owner settings, other files, is in a note named after it
(`<workflow>.md`) beside it. GitHub runs only `.yml`/`.yaml` files here,
and no workflow's `paths` match a `.md` file, so editing a note triggers
nothing. Rename a note with its workflow. The rule: CLAUDE.md, "Comments in
files that run CI".

| Workflow | Runs on | Does | Notes |
| --- | --- | --- | --- |
| `image-<name>.yml` | PRs and pushes to main touching the image | `_build-image.yml` for that image | [_build-image.md](_build-image.md#callers-image-nameyml) |
| `_build-image.yml` | called | verify (lint, build, smoke test); publish (push, publish-skip) | [_build-image.md](_build-image.md) |
| `build-image-branch.yml` | dispatch | one image or all, at any ref: test tags | [build-image-branch.md](build-image-branch.md) |
| `_discover-images.yml` | called | the image folders as a JSON list | [_discover-images.md](_discover-images.md) |
| `image-scan.yml` | Fridays 19:30 Vienna; dispatch; PRs touching it or the scanner pin | CVE scan of every published image; `scanner-age` | [image-scan.md](image-scan.md) |
| `checks.yml` | PRs and pushes to main touching `shared/` or `images/` | synced copies match `shared/`; every unit test | [checks.md](checks.md) |

Also: [../dependabot.md](../dependabot.md) (Dependabot), and
[tool-images/README.md](../../tool-images/README.md) (the pinned tool
images). Contracts and conventions: [CLAUDE.md](../../CLAUDE.md).
