Container images without much content, to use as deploy-dummies. 
But still nice enough to look at to keep deployed on "medium" timescales.

## Images

| Image | What it shows | Live |
| --- | --- | --- |
| `ghcr.io/idlinglight/phw-gradient-ripple` | A slowly drifting gradient; clicks and taps make water ripples. | [gradient.phw.salient.at](https://gradient.phw.salient.at) |
| `ghcr.io/idlinglight/phw-snake` | A small snake game that plays itself until someone takes over (keys, swipes, taps). | [snake.phw.salient.at](https://snake.phw.salient.at) |
| `ghcr.io/idlinglight/phw-europe-quiz` | A map quiz: find Europe's countries by name, then by their capitals (click or tap; zoom and pan). | [europe-quiz.phw.salient.at](https://europe-quiz.phw.salient.at) |

The live instances are run by the repo owner and may lag `main`:
`/version.txt` shows the commit each one runs.

All images: non-root nginx on port **8080**, `/healthz` for probes,
`/version.txt` with the build's commit SHA, read-only root filesystem OK
(needs a writable `/tmp`).

```sh
docker run --rm --read-only --tmpfs /tmp -p 8080:8080 \
  ghcr.io/idlinglight/phw-gradient-ripple:latest
```

Details and conventions: [CLAUDE.md](CLAUDE.md).
