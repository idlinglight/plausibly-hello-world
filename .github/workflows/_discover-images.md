# `_discover-images.yml`

Reusable: the image folders under `images/` (a folder with a `Dockerfile`
is an image) as a JSON list. Editing this file triggers
nothing; see [README.md](README.md).

- **Used by** `build-image-branch.yml` (`-f image=all`, a matrix) and
  `image-scan.yml` (the images its one job scans).
- **Name rule**: a valid GHCR path component (`^[a-z0-9]+([._-][a-z0-9]+)*$`).
  `_build-image.yml`'s lint checks its input against the same rule; change
  both together.
- **`all` is reserved**: it is the dispatch's word for every image, so a
  folder of that name could never be built alone.
