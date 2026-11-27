# Build context: this folder. Image contract (base, COPY-only, runtime,
# endpoints): CLAUDE.md "Image contract". The base is pinned by its index
# digest (all platforms); the tag beside it names the line it comes from.
FROM nginx/nginx-unprivileged:1.30-alpine-slim@sha256:04c98c78c1de60ddeada00d7d2207dcd146ecd07b61b9941c9a5799cfb258d28

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY site/ /usr/share/nginx/html/

# Served as /version.txt: the build's commit (build arg GIT_SHA).
ARG GIT_SHA=dev
COPY <<EOF /usr/share/nginx/html/version.txt
${GIT_SHA}
EOF
