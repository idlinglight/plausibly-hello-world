# Pin holder, never built. The vulnerability scanner image that
# .github/workflows/image-scan.yml runs — read from the FROM line below.
#
# Why a Dockerfile: Dependabot's github-actions ecosystem only sees `uses:`
# lines, so an image referenced from a `run:` step would never get bumped.
# As a FROM line it gets the same weekly digest/tag PRs (and 3-day cooldown)
# as the image folders. Digest-pinned, enforced by the workflow.
#
# This folder is in image-scan.yml's pull_request `paths:` — a bump PR runs
# the new scanner against the published images before merge.
FROM ghcr.io/anchore/grype:v0.121.0@sha256:621d56d1d68106b787022c81546f7e0a36202a25d1239f0c20195fab8c16f7ea
