# Pin holder, never built. The BuildKit daemon image that
# .github/workflows/_build-image.yml runs its builder on (buildx
# docker-container driver) — read from the FROM line below.
#
# Why a Dockerfile: Dependabot's github-actions ecosystem only sees `uses:`
# lines, so an image referenced from a `run:` step would never get bumped.
# As a FROM line it gets the same weekly digest/tag PRs (and 3-day cooldown)
# as the image folders. Digest-pinned, enforced by the workflow.
#
# This folder is in every image caller's `paths:` — a bump here re-verifies
# (PR) and re-publishes (main) every image, like any build-logic change.
FROM moby/buildkit:v0.34.1@sha256:99368f3e46177c6405b9740e4461d91cee004128daeecca78d4ceac50ec1da5c
