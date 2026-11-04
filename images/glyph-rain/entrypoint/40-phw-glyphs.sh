#!/bin/sh
# glyph-rain: which glyph sets the page shows, decided once at container
# start. The base image's /docker-entrypoint.sh runs every executable *.sh
# in /docker-entrypoint.d/ before it starts nginx; this one runs as uid 101.
#
# Two documented switches, neither of them secret:
#   env   PHW_GLYPHS=music                → musical symbols
#   file  /etc/phw/glyphs, content runes  → runes (e.g. a secret mounted as
#                                           a file; one trailing newline ok)
#   both                                  → both sets, mixed
#   neither                               → Egyptian hieroglyphs
#
# Output: /tmp/phw/glyphs.json, served as /glyphs.json (site/glyphs.json is
# a symlink to it: the root filesystem may be read-only, /tmp is writable).
# It holds fixed tokens only. A switch's value is never written or logged:
# the page and the log can only say whether a switch is unset, matches, or
# holds something else.
#
# Never fails the start (the entrypoint runs these under set -e): on any
# problem the page shows the default and says the runtime file is missing.
# POSIX sh (busybox ash in the image): no eval, every expansion quoted.

ENV_VALUE=music
SECRET_FILE=/etc/phw/glyphs
SECRET_VALUE=runes
OUT_DIR=/tmp/phw

ME=$(basename "$0")
log() {
    if [ -z "${NGINX_ENTRYPOINT_QUIET_LOGS:-}" ]; then echo "$ME: $*"; fi
}

# env: unset | match | other
if [ -z "${PHW_GLYPHS:-}" ]; then
    env_state=unset
    log "PHW_GLYPHS: not set (or empty)"
elif [ "$PHW_GLYPHS" = "$ENV_VALUE" ]; then
    env_state=match
    log "PHW_GLYPHS: matches"
else
    env_state=other
    log "PHW_GLYPHS: set, but not to the value this image knows: ignored (the value isn't logged)"
fi

# file: absent | match | other | unreadable | directory
if [ -d "$SECRET_FILE" ]; then
    file_state=directory
    log "$SECRET_FILE: is a directory: mount the volume at $(dirname "$SECRET_FILE"), the folder that holds the file"
elif [ ! -e "$SECRET_FILE" ]; then
    file_state=absent
    log "$SECRET_FILE: not present"
elif [ ! -r "$SECRET_FILE" ]; then
    file_state=unreadable
    log "$SECRET_FILE: present, but not readable by uid $(id -u)"
else
    # At most 64 bytes; $(...) drops trailing newlines, then one CR goes.
    content=$(head -c 64 "$SECRET_FILE" 2>/dev/null)
    content=${content%"$(printf '\r')"}
    if [ "$content" = "$SECRET_VALUE" ]; then
        file_state=match
        log "$SECRET_FILE: matches"
    else
        file_state=other
        log "$SECRET_FILE: present, but not the value this image knows: ignored (the content isn't logged)"
    fi
    content=
fi

glyphs=
if [ "$env_state" = match ]; then glyphs='"music"'; fi
if [ "$file_state" = match ]; then glyphs="${glyphs:+$glyphs,}\"runes\""; fi
if [ -z "$glyphs" ]; then glyphs='"hieroglyphs"'; fi

if mkdir -p "$OUT_DIR" 2>/dev/null &&
    printf '{"glyphs":[%s],"env":"%s","file":"%s"}\n' "$glyphs" "$env_state" "$file_state" \
        >"$OUT_DIR/glyphs.json" 2>/dev/null; then
    log "glyphs: $(echo "$glyphs" | tr -d '"' | sed 's/,/, /')"
else
    echo "$ME: can't write $OUT_DIR/glyphs.json: the page shows the default" >&2
fi
exit 0
