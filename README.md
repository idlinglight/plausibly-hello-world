Container images without much content, to use as deploy-dummies. 
But still nice enough to look at to keep deployed on "medium" timescales.

## Images

| Image | What it shows | Live |
| --- | --- | --- |
| `ghcr.io/idlinglight/phw-gradient-ripple` | A slowly drifting gradient; clicks and taps make water ripples. | [gradient.phw.salient.at](https://gradient.phw.salient.at) |
| `ghcr.io/idlinglight/phw-snake` | A small snake game that plays itself until someone takes over (keys, swipes, taps). | [snake.phw.salient.at](https://snake.phw.salient.at) |
| `ghcr.io/idlinglight/phw-europe-quiz` | A map quiz: find Europe's countries by name, then by their capitals (click or tap; zoom and pan). | [europe-quiz.phw.salient.at](https://europe-quiz.phw.salient.at) |
| `ghcr.io/idlinglight/phw-vienna-districts` | A map quiz in German: find Vienna's 23 districts by name, then by number (click or tap; zoom and pan). | [vienna-districts.phw.salient.at](https://vienna-districts.phw.salient.at) |
| `ghcr.io/idlinglight/phw-japan-quiz` | A map quiz: find Japan's main islands, its 8 regions and 47 prefectures, then the prefectures by their capitals, each name also in kanji and hiragana; the asked name links to its Wikipedia article (click or tap; zoom and pan). | [japan-quiz.phw.salient.at](https://japan-quiz.phw.salient.at) |
| `ghcr.io/idlinglight/phw-world-quiz` | A map quiz on Buckminster Fuller's Dymaxion (Airocean) projection: find the world's 197 countries by name, then by their capitals, first without the smallest states, then with all of them; the asked name links to its Wikipedia article (click or tap; zoom and pan; pick a round on the card). | [world-quiz.phw.salient.at](https://world-quiz.phw.salient.at) |
| `ghcr.io/idlinglight/phw-south-america-quiz` | A map quiz: find South America's countries and French Guiana by name, then by their capitals (click or tap; zoom and pan). | [south-america-quiz.phw.salient.at](https://south-america-quiz.phw.salient.at) |
| `ghcr.io/idlinglight/phw-east-asia-quiz` | A map quiz: find the countries of East and Southeast Asia by name, then by their capitals (click or tap; zoom and pan). | [east-asia-quiz.phw.salient.at](https://east-asia-quiz.phw.salient.at) |
| `ghcr.io/idlinglight/phw-glyph-rain` | Glyphs raining down and fading, Egyptian hieroglyphs by default; two switches read at startup change the set (below). Meant to run behind an auth layer, so there's no public instance. | — |

The live instances are run by the repo owner and may lag `main`:
`/version.txt` shows the commit each one runs.

All images: non-root nginx on port **8080**, `/healthz` for probes,
`/version.txt` with the build's commit SHA, read-only root filesystem OK
(needs a writable `/tmp`).

```sh
docker run --rm --read-only --tmpfs /tmp -p 8080:8080 \
  ghcr.io/idlinglight/phw-gradient-ripple:latest
```

`phw-glyph-rain` shows which switches reached the container when it
started: env `PHW_GLYPHS=music` → musical symbols, a file
`/etc/phw/glyphs` containing exactly `runes` (one LF or CRLF after it is
fine; e.g. a secret mounted as a file) → runes, both → the two mixed. The
values aren't secret, and the page and the log only ever say whether a
switch matched, never what it held.

```sh
printf 'runes\n' > glyphs
docker run --rm --read-only --tmpfs /tmp -p 8080:8080 \
  -e PHW_GLYPHS=music -v "$PWD/glyphs:/etc/phw/glyphs:ro" \
  ghcr.io/idlinglight/phw-glyph-rain:latest
```

Details and conventions: [CLAUDE.md](CLAUDE.md).
