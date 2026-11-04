# `build-image-branch.yml`

On-demand builds: verify + publish `sha-<short7>` of one image folder, or of
all of them, at any ref. Editing this file triggers nothing; see
[README.md](README.md).

```sh
gh workflow run build-image-branch.yml --ref <branch> -f image=<name>   # one image
gh workflow run build-image-branch.yml --ref <branch> -f image=all      # every image
```

- **For**: test tags of a PR head, a Dependabot branch, a new image whose
  caller isn't on main yet. One image needs no discovery (job `one`); a bad
  name fails `_build-image.yml`'s lint step before anything is built. `all`
  goes through `_discover-images.yml`, which rejects a folder named `all`.
- **The ref's own files run**: GitHub offers a dispatch only for workflows
  on the default branch, but the run uses the workflow files **at `--ref`**,
  so changes to the build itself are exercised too. A ref without this
  workflow's dispatch fails with 422 ("does not have workflow_dispatch
  trigger"): rebase the branch, or `@dependabot rebase` a Dependabot PR.
- **Always publishes**: publish-skip (`_build-image.md`) applies to pushes
  only, so a test tag you asked for is never skipped.
- **On main only to force a republish**: there the publish also moves
  `latest` (while the commit is the head) and queues in the same
  concurrency groups as main's own publishes.
- **History**: before 2026-11-04 (#19, #21) test tags came from pushing to
  `build-image/<topic>`, which built and published every image (about 19
  jobs), and each caller had a dispatch of its own.
