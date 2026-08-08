# Caption fonts

Drop `.ttf` files here and they are installed into the backend image and
picked up by fontconfig at build time.

`pipeline/captions.py` asks for, in order: **Poppins**, **Montserrat**,
**DejaVu Sans**. The last one ships with the base image, so captions always
render; the first two only apply if you add them.

To match the existing videos, add Poppins Bold:

```bash
curl -L -o Poppins-Bold.ttf \
  "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf"
```

Fonts are not committed — they carry their own licences, and the pipeline
works without them.
