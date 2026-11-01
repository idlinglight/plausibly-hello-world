# Build context: this folder. Image contract: /CLAUDE.md "Image contract".
#
# Base image is digest-pinned (index digest, all platforms); the tag alongside
# is human-readable documentation + Dependabot's bump target. Patches arrive as
# weekly Dependabot digest bumps — for an urgent advisory, bump manually.
#
# No RUN in this file on purpose: COPY-only means multi-arch builds need no
# QEMU emulation, and the image gains nothing beyond the base + static files.
FROM nginxinc/nginx-unprivileged:1.30-alpine-slim@sha256:5d8bb9437d74a600ec5dbf90c035451c724dc33eac8d3a71078f6f8612c345f6

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY site/ /usr/share/nginx/html/

# Served as /version.txt; CI passes the short commit SHA.
ARG GIT_SHA=dev
COPY <<EOF /usr/share/nginx/html/version.txt
${GIT_SHA}
EOF
