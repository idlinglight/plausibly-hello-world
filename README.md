Container images without much content, to use as deploy-dummies. 
But still nice enough to look at to keep deployed on "medium" timescales.

## Images

| Image | What it shows |
| --- | --- |
| `ghcr.io/idlinglight/phw-gradient-ripple` | A slowly drifting gradient; clicks and taps make water ripples. |
| `ghcr.io/idlinglight/phw-snake` | A small snake game that plays itself until someone takes over (keys, swipes, taps). |
| `ghcr.io/idlinglight/phw-europe-quiz` | A map quiz: find Europe's countries by name, then by their capitals (click or tap; zoom and pan). |

All images: non-root nginx on port **8080**, `/healthz` for probes,
`/version.txt` with the build's commit SHA, read-only root filesystem OK
(needs a writable `/tmp`).

```sh
docker run --rm --read-only --tmpfs /tmp -p 8080:8080 \
  ghcr.io/idlinglight/phw-gradient-ripple:latest
```

Details and conventions: [CLAUDE.md](CLAUDE.md).
