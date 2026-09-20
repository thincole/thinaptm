# Seedvis API v2.0

Base URL: `https://seedvis.com/api/v1`
Google-compatible base URL: `https://seedvis.com/api/v1/google`

## Rules for AI agents

1. Pick the model id from `GET https://seedvis.com/api/v1/models` and read its `modes[]`: each mode says which endpoint to call and how many images it needs (`images.min`/`images.max`).
2. Send reference images **inline** in `reference_images` (or the field named by the mode): a public `https://` URL, a `data:image/…;base64,` URL or a raw base64 string. Mixing is fine. Max 10 images, 20 MiB each, 40 MiB of base64 per request. To keep a base64 image's file name, send `{"data": "<base64>", "file_name": "photo.png"}` (`file_name` is optional).
3. Never guess whether an image was used: every 2xx response echoes `references[]` and `mode`. Compare the count with what you sent.
4. A `text-*` mode rejects images and an `image-to-*` mode requires them — the `400` tells you the right mode. Sending the wrong count is never silently accepted.
5. **`status: queued` or `processing` is a success.** Follow `next.url` (it already contains `?wait=60`) until `is_final` is `true`. Never resend the request: a resend is a new job and a new charge.
6. Always send `Idempotency-Key: <uuid>`; then a retry after a network error returns the same job.
7. Read errors only when HTTP ≥ 400 or `status` is `failed`: native `errors["field[i]"]`, OpenAI `error.param`, Google `error.message`.

## Copy this client

Copy one of these as-is instead of writing your own polling loop. Both submit with an `Idempotency-Key`, treat `queued`/`processing` as success, follow `next.url` and return the output URLs.

```python
import base64, os, time, uuid, requests

BASE = "https://seedvis.com/api/v1"
HEADERS = {"Authorization": f"Bearer {os.environ['SEEDVIS_API_KEY']}"}

def generate(model: str, prompt: str, images: list | None = None, video: str | None = None, **params) -> list[str]:
    """images: public URLs, data URLs, base64 or {"data", "file_name"} — mixed is fine. Returns output URLs.
    video: source MP4/MOV/WebM URL or base64 — only for a video-to-video mode."""
    body = {"model": model, "prompt": prompt, **params}
    if images:
        body["reference_images"] = images
    if video:
        body["video"] = video
    headers = {**HEADERS, "Idempotency-Key": str(uuid.uuid4())}  # a retry never creates a 2nd job
    r = requests.post(f"{BASE}/developer/generations", json=body, headers=headers, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(r.json())          # errors["field[i]"] says exactly what to fix
    data = r.json()["data"]
    while not data["is_final"]:               # queued/processing = success, keep waiting
        time.sleep(data["next"].get("after_seconds", 5))
        data = requests.get(data["next"]["url"], headers=HEADERS, timeout=90).json()["data"]
    if data["status"] == "failed":
        raise RuntimeError(data["error"])
    return [o["url"] for o in data["outputs"]]

def as_image(path: str) -> dict:
    # optional "file_name" keeps the file name in the stored reference URL (…/references/{user}/photo.png)
    return {"file_name": os.path.basename(path), "data": base64.b64encode(open(path, "rb").read()).decode()}

# A local file becomes a reference image in one request:
print(generate("MODEL_ID_FROM_GET_MODELS", "Animate this photo", [as_image("photo.png")]))
```

```javascript
import { readFile } from "node:fs/promises";

const BASE = "https://seedvis.com/api/v1";
const HEADERS = { Authorization: `Bearer ${process.env.SEEDVIS_API_KEY}` };
const sleep = (s) => new Promise((r) => setTimeout(r, s * 1000));

// images: public URLs, data URLs, base64 or { data, file_name } — mixed is fine. Resolves to output URLs.
export async function generate(model, prompt, images = [], params = {}) {
  const body = { model, prompt, ...params, ...(images.length ? { reference_images: images } : {}) };
  const res = await fetch(`${BASE}/developer/generations`, {
    method: "POST",
    headers: { ...HEADERS, "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(body),
  });
  let json = await res.json();
  if (!res.ok) throw new Error(JSON.stringify(json)); // errors["field[i]"] says what to fix
  let data = json.data;
  while (!data.is_final) {                             // queued/processing = success, keep waiting
    await sleep(data.next.after_seconds ?? 5);
    data = (await (await fetch(data.next.url, { headers: HEADERS })).json()).data;
  }
  if (data.status === "failed") throw new Error(JSON.stringify(data.error));
  return data.outputs.map((o) => o.url);
}

// optional file_name keeps the file name in the stored reference URL (…/references/{user}/photo.png)
const photo = { file_name: "photo.png", data: (await readFile("photo.png")).toString("base64") };
console.log(await generate("MODEL_ID_FROM_GET_MODELS", "Animate this photo", [photo]));
```

```bash
# 1) submit (a data URL works the same as a public URL)
curl -s -X POST "https://seedvis.com/api/v1/developer/generations" \
  -H "Authorization: Bearer $SEEDVIS_API_KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"model":"MODEL_ID_FROM_GET_MODELS","prompt":"Animate this photo","reference_images":["https://example.com/photo.png"]}'
# → {"success":true,"status":202,"data":{"id":"…","status":"queued","is_final":false,"next":{"action":"poll","url":"…?wait=60"}}}

# 2) wait: the server holds the connection up to 60 s and answers as soon as the job is final
curl -s "https://seedvis.com/api/v1/developer/generations/REQUEST_ID?wait=60" -H "Authorization: Bearer $SEEDVIS_API_KEY"
# → {"success":true,"status":200,"data":{"status":"completed","is_final":true,"outputs":[{"type":"image","url":"https://cdn…"}]}}
```

### Video to video (curl)

```bash
curl -sS -X POST https://seedvis.com/api/v1/developer/generations \
  -H "Authorization: Bearer $SEEDVIS_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"model":"Omni-Flash","prompt":"Replace the outfit and background, keep the audio","video":"https://cdn.example.com/source.mp4","reference_images":["https://cdn.example.com/outfit.png"]}'
```

A local file goes in the same request as a form part — no upload step, no temporary link:

```bash
curl -sS -X POST https://seedvis.com/api/v1/developer/generations \
  -H "Authorization: Bearer $SEEDVIS_API_KEY" \
  -F "model=Omni-Flash" \
  -F "prompt=Replace the outfit, keep the audio" \
  -F "video=@/path/to/source.mp4" \
  -F "reference_images[]=https://cdn.example.com/outfit.png"
```

Send base64 instead of a URL with `"video": "data:video/mp4;base64,…"`. The reply carries `mode: video-to-video`; poll `next.url` exactly like any other mode.


## Authentication

Send the API key in a header. Never put it in the URL.

- `Authorization: Bearer YOUR_API_KEY`
- `X-API-Key: YOUR_API_KEY`
- `x-goog-api-key: YOUR_API_KEY` — Google-compatible endpoints

## Models

`GET https://seedvis.com/api/v1/models` is the single source of truth: every public model id, its `family`, `modes[]` (endpoint + image rule per mode), the complete parameter schema with allowed values and defaults, and `documentation_modes[]` with a ready request example per mode.

Models that are disabled, under maintenance, not released yet, or browser-only are absent from that list and from this document; sending one is rejected with `404 model_not_found` and the message lists the valid ids.

## Reference images

Reference images travel inline with the request. Every image field accepts any of these forms, and one request may mix them:

| Form | Example |
|---|---|
| Public image URL | `"https://example.com/photo.png"` |
| Data URL | `"data:image/png;base64,iVBORw0KGgo…"` |
| Raw base64 | `"iVBORw0KGgoAAAANSUhEUgAA…"` |
| Base64 + `file_name` (keeps the file name) | `{"data":"iVBORw0KGgo…","file_name":"photo.png"}` or `"data:image/png;file_name=photo.png;base64,iVBORw0KGgo…"` |
| OpenAI object | `{"type":"image_url","image_url":{"url":"https://…"}}` or `{"b64_json":"…"}` |
| Gemini part | `{"inlineData":{"mimeType":"image/png","data":"…"}}` or `{"fileData":{"fileUri":"https://…"}}` |
| FlipAI object | `{"image_base64":"…","mime_type":"image/png"}` |
| Multipart | `-F "image=@photo.png"` |

| Endpoint | Field | Also accepted |
|---|---|---|
| `POST /developer/generations` | `reference_images` | `images`, `image`, `image_url`, `start_image` + `end_image` (batch-frame), `lastFrame` |
| `POST /images/edits` | `image` | `images`, `reference_images` |
| `POST /google/v1beta/interactions` | `reference_images` | `images`, or image parts inside `input` |
| `POST /google/v1beta/models/{id}:predictLongRunning` | `instances[0].image`, `lastFrame`, `referenceImages` | Google `{"image":{"bytesBase64Encoded":…}}` objects |

- Limits: 10 images per request, 20 MiB per image after decoding, 40 MiB of inline data per request. PNG, JPEG or WebP.
- Seedvis stores every reference on its own storage before the model runs; the response `references[]` shows the stored URL for each image you sent, in order.
- Anything that is not an image is rejected with `400` and the exact position, e.g. `errors["reference_images[1]"]`. Nothing is dropped silently.

### Keep the file name: `file_name`

- `file_name` is an **optional** attribute of every image item, on every model and endpoint that accepts images (`reference_images`, `images`, `image`, `lastFrame`, …).
- Sending images as base64 and want to keep the file name? Send the item as an object with `data` + `file_name`: `{"data": "<base64>", "file_name": "photo.png"}`. Raw base64 carries no name, so without `file_name` the image gets a random name.
- The stored reference URL (echoed in `references[]`) then keeps that name: `…/references/{user}/photo.png`; the same name again becomes `photo-1.png`, `photo-2.png`, …
- Image URLs and multipart files already carry their own name — nothing to add.

```json
{"model": "MODEL_ID_FROM_GET_MODELS", "prompt": "Animate this photo",
 "reference_images": [{"data": "iVBORw0KGgo…", "file_name": "photo.png"}, "https://example.com/scene.png"]}
```

### Common mistakes

- Sending images to a `text-to-*` mode, or none to an `image-to-*` mode → `400` naming the mode that fits your image count.
- `batch-frame` needs two frames: `image` (or `start_image`) **and** `lastFrame` (or `end_image`).
- Treating `202` / `status: queued` as an error and resending → duplicate jobs and charges. Follow `next.url`.
- `mask` (OpenAI inpainting) is not supported.
- More than 40 MiB of base64 → host the large images and send URLs.

## Source video (video-to-video)

Modes whose input rule says `1 video` read the field `video`. Everything else stays the same: the prompt describes the change, and reference images keep their own field.

| Form | Example |
|---|---|
| Public URL | `"video": "https://cdn.example.com/source.mp4"` |
| Data URL | `"video": "data:video/mp4;base64,AAAAIGZ0eXB…"` |
| Raw base64 | `"video": "AAAAIGZ0eXB…"` |
| File upload | `multipart/form-data` with a `video` file part — for local tools that have the file on disk |

- One video per request. MP4, MOV or WebM, at most 100 MiB (95 MiB for an uploaded file part).
- A file part is uploaded inside this same request, the one that charges credits: there is no separate upload step and no orphan files.
- The video is copied to Seedvis storage before the job starts, so a link that expires later does not break the generation.
- Sending `video` to a mode that does not accept it is a `400`, and so is leaving it out of `video-to-video` — the error names the mode to use.

## Results, polling and async

One lifecycle for every endpoint. Every 2xx body — first response and every poll — carries the same fields:

| Field | Meaning |
|---|---|
| `status` | `queued` → `processing` → `completed` or `failed` |
| `is_final` | `false` while running, `true` for `completed`/`failed` |
| `next` | `{"action":"poll","url":"…?wait=60","after_seconds":10}` while running; `{"action":"done"}` when final |
| `message` | Plain-language sentence saying what to do (e.g. "Accepted. Generation is running. Poll next.url; do not resend.") |
| `mode` | The mode that ran, inferred from your images |
| `outputs[]` | `[]` until final; then `[{type, url}]` |
| `references[]` | The reference images that were used |
| `error` | Present **only** when `status` is `failed`: `{code, message}` |

- **`queued` and `processing` are not errors.** Video always answers `queued` immediately and takes 1–10 minutes. Poll `next.url`; never resend.
- `GET https://seedvis.com/api/v1/developer/generations/{id}?wait=60` holds the connection for up to 60 seconds and returns as soon as the job is final, so one call per minute is enough.
- Image endpoints (`/images/*`, `/google/v1beta/interactions`) wait up to 90 seconds inline. Not finished in time → `202` with the same fields; keep polling.
- Send `Idempotency-Key: <uuid>` with every submit. Without it, an identical request within 120 seconds still returns the existing job (`Idempotency-Replayed: true`) instead of starting a second one.
- A webhook delivers the terminal result too (see Webhooks); a poll loop can then be a slow safety net.
- Result URLs are served from the Seedvis CDN. Download the file into your own storage before the retention window of your plan expires.

## Models and generation endpoints

Same model id, several modes: the mode is inferred from the images you send (or set with `mode`) and echoed back. Each mode below is one request shape.

### GPT Image 2

Model id: `gpt-image-2`

> OpenAI drop-in: keep your OpenAI Images request shape, change the Base URL to `https://seedvis.com/api/v1` and use a Seedvis API key. `/images/generations` is text-to-image; `/images/edits` is image-to-image — same model id, as in OpenAI.

#### GPT Image 2 — text-to-image

`POST /images/generations` · `mode: text-to-image` · **no images (sending one is a 400)**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"gpt-image-2"` |
| `prompt` | `string` | yes | — |
| `n` | `integer` | no | range `1–8`; default `1` |
| `size` | `string` | no | `"auto"`, `"1:1"`, `"3:4"`, `"9:16"`, `"4:3"`, `"16:9"`, `"2:3"`, `"3:2"`, `"21:9"`; Aspect ratio |
| `quality` | `string` | no | `"auto"` |
| `response_format` | `string` | no | `"url"` |

Request:

```json
{
    "model": "gpt-image-2",
    "prompt": "A cinematic product photo",
    "n": 1,
    "size": "auto",
    "quality": "auto",
    "response_format": "url"
}
```

Response:

```json
{
    "created": 1788192000,
    "data": [
        {
            "url": "https://cdn.seedvis.com/result.png"
        }
    ]
}
```

Full URL: `https://seedvis.com/api/v1/images/generations`

#### GPT Image 2 — image-to-image

`POST /images/edits` · `mode: image-to-image` · **1–10 images: image**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"gpt-image-2"` |
| `prompt` | `string` | yes | — |
| `image` | `image[] (URL or base64)` | yes | range `1–10`; 1–10 images, URLs and base64 may be mixed. Aliases: images. |
| `image[].file_name` | `string` | no | Optional. Only for base64 images: send the image as {"data": "<base64>", "file_name": "photo.png"} and the stored reference URL keeps that name (…/references/{user}/photo.png, then photo-1.png, photo-2.png for repeats). Without file_name a base64 image gets a random name. Image URLs and multipart files keep their own name. |
| `n` | `integer` | no | range `1–8`; default `1` |
| `size` | `string` | no | `"auto"`, `"1:1"`, `"3:4"`, `"9:16"`, `"4:3"`, `"16:9"`, `"2:3"`, `"3:2"`, `"21:9"`; Aspect ratio |
| `quality` | `string` | no | `"auto"` |
| `response_format` | `string` | no | `"url"` |

Request:

```json
{
    "model": "gpt-image-2",
    "prompt": "A cinematic product photo",
    "image": [
        "https://cdn.seedvis.com/reference.png",
        {
            "data": "iVBORw0KGgo…",
            "file_name": "photo.png"
        }
    ],
    "n": 1,
    "size": "auto",
    "quality": "auto",
    "response_format": "url"
}
```

Response:

```json
{
    "created": 1788192000,
    "data": [
        {
            "url": "https://cdn.seedvis.com/result.png"
        }
    ]
}
```

Full URL: `https://seedvis.com/api/v1/images/edits`

### Nano Banana

Model ids in this family: `GEM_PIX_2`, `NARWHAL`, `HARBOR_SEAL`.

#### Nano Banana Pro — text-to-image

`POST /google/v1beta/interactions` · `mode: text-to-image` · **no images (sending one is a 400)**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"GEM_PIX_2"` |
| `input` | `string or content[]` | yes | Prompt text, or Gemini-style parts (text + inlineData/fileData images). |
| `mode` | `string` | no | `"text-to-image"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `count` | `integer` | no | range `1–8`; default `1`; Count |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`, `"1:1"`, `"4:3"`, `"3:4"`; default `"16:9"`; Aspect ratio |
| `upscale_image` | `select` | no | `"none"`, `"2k"`, `"4k"`; default `"none"`; Upscale |

Request:

```json
{
    "model": "GEM_PIX_2",
    "input": "Create a clean product poster",
    "aspect_ratio": "16:9",
    "upscale_image": "none",
    "count": 1
}
```

Response:

```json
{
    "id": "REQUEST_ID",
    "status": "completed",
    "is_final": true,
    "model": "GEM_PIX_2",
    "mode": "text-to-image",
    "outputs": [
        {
            "type": "image",
            "url": "https://cdn.seedvis.com/result.png"
        }
    ],
    "references": []
}
```

Full URL: `https://seedvis.com/api/v1/google/v1beta/interactions`

#### Nano Banana Pro — image-to-image

`POST /google/v1beta/interactions` · `mode: image-to-image` · **1–10 images: reference_images**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"GEM_PIX_2"` |
| `input` | `string or content[]` | yes | Prompt text, or Gemini-style parts (text + inlineData/fileData images). |
| `reference_images` | `image[] (URL or base64)` | yes | range `1–10`; 1–10 images, URLs and base64 may be mixed. Aliases: images, image parts inside input. |
| `reference_images[].file_name` | `string` | no | Optional. Only for base64 images: send the image as {"data": "<base64>", "file_name": "photo.png"} and the stored reference URL keeps that name (…/references/{user}/photo.png, then photo-1.png, photo-2.png for repeats). Without file_name a base64 image gets a random name. Image URLs and multipart files keep their own name. |
| `mode` | `string` | no | `"image-to-image"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `count` | `integer` | no | range `1–8`; default `1`; Count |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`, `"1:1"`, `"4:3"`, `"3:4"`; default `"16:9"`; Aspect ratio |
| `upscale_image` | `select` | no | `"none"`, `"2k"`, `"4k"`; default `"none"`; Upscale |

Request:

```json
{
    "model": "GEM_PIX_2",
    "input": "Create a clean product poster",
    "reference_images": [
        "https://cdn.seedvis.com/reference.png",
        {
            "data": "iVBORw0KGgo…",
            "file_name": "photo.png"
        }
    ],
    "aspect_ratio": "16:9",
    "upscale_image": "none",
    "count": 1
}
```

Response:

```json
{
    "id": "REQUEST_ID",
    "status": "completed",
    "is_final": true,
    "model": "GEM_PIX_2",
    "mode": "image-to-image",
    "outputs": [
        {
            "type": "image",
            "url": "https://cdn.seedvis.com/result.png"
        }
    ],
    "references": [
        {
            "field": "reference_images",
            "index": 0,
            "role": null,
            "source": "url",
            "url": "https://cdn.seedvis.com/references/…png"
        }
    ]
}
```

Full URL: `https://seedvis.com/api/v1/google/v1beta/interactions`

#### Nano Banana 2 — text-to-image

`POST /google/v1beta/interactions` · `mode: text-to-image` · **no images (sending one is a 400)**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"NARWHAL"` |
| `input` | `string or content[]` | yes | Prompt text, or Gemini-style parts (text + inlineData/fileData images). |
| `mode` | `string` | no | `"text-to-image"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `count` | `integer` | no | range `1–8`; default `1`; Count |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`, `"1:1"`, `"4:3"`, `"3:4"`; default `"16:9"`; Aspect ratio |
| `upscale_image` | `select` | no | `"none"`, `"2k"`, `"4k"`; default `"none"`; Upscale |

Request:

```json
{
    "model": "NARWHAL",
    "input": "Create a clean product poster",
    "aspect_ratio": "16:9",
    "upscale_image": "none",
    "count": 1
}
```

Response:

```json
{
    "id": "REQUEST_ID",
    "status": "completed",
    "is_final": true,
    "model": "NARWHAL",
    "mode": "text-to-image",
    "outputs": [
        {
            "type": "image",
            "url": "https://cdn.seedvis.com/result.png"
        }
    ],
    "references": []
}
```

Full URL: `https://seedvis.com/api/v1/google/v1beta/interactions`

#### Nano Banana 2 — image-to-image

`POST /google/v1beta/interactions` · `mode: image-to-image` · **1–10 images: reference_images**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"NARWHAL"` |
| `input` | `string or content[]` | yes | Prompt text, or Gemini-style parts (text + inlineData/fileData images). |
| `reference_images` | `image[] (URL or base64)` | yes | range `1–10`; 1–10 images, URLs and base64 may be mixed. Aliases: images, image parts inside input. |
| `reference_images[].file_name` | `string` | no | Optional. Only for base64 images: send the image as {"data": "<base64>", "file_name": "photo.png"} and the stored reference URL keeps that name (…/references/{user}/photo.png, then photo-1.png, photo-2.png for repeats). Without file_name a base64 image gets a random name. Image URLs and multipart files keep their own name. |
| `mode` | `string` | no | `"image-to-image"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `count` | `integer` | no | range `1–8`; default `1`; Count |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`, `"1:1"`, `"4:3"`, `"3:4"`; default `"16:9"`; Aspect ratio |
| `upscale_image` | `select` | no | `"none"`, `"2k"`, `"4k"`; default `"none"`; Upscale |

Request:

```json
{
    "model": "NARWHAL",
    "input": "Create a clean product poster",
    "reference_images": [
        "https://cdn.seedvis.com/reference.png",
        {
            "data": "iVBORw0KGgo…",
            "file_name": "photo.png"
        }
    ],
    "aspect_ratio": "16:9",
    "upscale_image": "none",
    "count": 1
}
```

Response:

```json
{
    "id": "REQUEST_ID",
    "status": "completed",
    "is_final": true,
    "model": "NARWHAL",
    "mode": "image-to-image",
    "outputs": [
        {
            "type": "image",
            "url": "https://cdn.seedvis.com/result.png"
        }
    ],
    "references": [
        {
            "field": "reference_images",
            "index": 0,
            "role": null,
            "source": "url",
            "url": "https://cdn.seedvis.com/references/…png"
        }
    ]
}
```

Full URL: `https://seedvis.com/api/v1/google/v1beta/interactions`

#### Nano Banana Lite — text-to-image

`POST /google/v1beta/interactions` · `mode: text-to-image` · **no images (sending one is a 400)**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"HARBOR_SEAL"` |
| `input` | `string or content[]` | yes | Prompt text, or Gemini-style parts (text + inlineData/fileData images). |
| `mode` | `string` | no | `"text-to-image"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `count` | `integer` | no | range `1–8`; default `1`; Count |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`, `"1:1"`, `"4:3"`, `"3:4"`; default `"16:9"`; Aspect ratio |
| `upscale_image` | `select` | no | `"none"`, `"2k"`, `"4k"`; default `"none"`; Upscale |

Request:

```json
{
    "model": "HARBOR_SEAL",
    "input": "Create a clean product poster",
    "aspect_ratio": "16:9",
    "upscale_image": "none",
    "count": 1
}
```

Response:

```json
{
    "id": "REQUEST_ID",
    "status": "completed",
    "is_final": true,
    "model": "HARBOR_SEAL",
    "mode": "text-to-image",
    "outputs": [
        {
            "type": "image",
            "url": "https://cdn.seedvis.com/result.png"
        }
    ],
    "references": []
}
```

Full URL: `https://seedvis.com/api/v1/google/v1beta/interactions`

#### Nano Banana Lite — image-to-image

`POST /google/v1beta/interactions` · `mode: image-to-image` · **1–10 images: reference_images**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"HARBOR_SEAL"` |
| `input` | `string or content[]` | yes | Prompt text, or Gemini-style parts (text + inlineData/fileData images). |
| `reference_images` | `image[] (URL or base64)` | yes | range `1–10`; 1–10 images, URLs and base64 may be mixed. Aliases: images, image parts inside input. |
| `reference_images[].file_name` | `string` | no | Optional. Only for base64 images: send the image as {"data": "<base64>", "file_name": "photo.png"} and the stored reference URL keeps that name (…/references/{user}/photo.png, then photo-1.png, photo-2.png for repeats). Without file_name a base64 image gets a random name. Image URLs and multipart files keep their own name. |
| `mode` | `string` | no | `"image-to-image"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `count` | `integer` | no | range `1–8`; default `1`; Count |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`, `"1:1"`, `"4:3"`, `"3:4"`; default `"16:9"`; Aspect ratio |
| `upscale_image` | `select` | no | `"none"`, `"2k"`, `"4k"`; default `"none"`; Upscale |

Request:

```json
{
    "model": "HARBOR_SEAL",
    "input": "Create a clean product poster",
    "reference_images": [
        "https://cdn.seedvis.com/reference.png",
        {
            "data": "iVBORw0KGgo…",
            "file_name": "photo.png"
        }
    ],
    "aspect_ratio": "16:9",
    "upscale_image": "none",
    "count": 1
}
```

Response:

```json
{
    "id": "REQUEST_ID",
    "status": "completed",
    "is_final": true,
    "model": "HARBOR_SEAL",
    "mode": "image-to-image",
    "outputs": [
        {
            "type": "image",
            "url": "https://cdn.seedvis.com/result.png"
        }
    ],
    "references": [
        {
            "field": "reference_images",
            "index": 0,
            "role": null,
            "source": "url",
            "url": "https://cdn.seedvis.com/references/…png"
        }
    ]
}
```

Full URL: `https://seedvis.com/api/v1/google/v1beta/interactions`

### Seedance

IMPORTANT NOTES SEEDANCE MODELS:Source: Seedance 2.5/2.0 Fast via Dola.Human References: Not supported (occasionally still able to create).Moderation: Dola is strict, with a high rejection rate. Prompt optimization is required (suggestions provided).Recommended for: API integration, optimized prompts, all-day use, and automatic retries on failure. Less suitable for beginners; consider this before upgrading.


Model ids in this family: `seedance_2.5`, `seedance_2.0_fast`.

#### Seedance 2.5 — text-to-video

`POST /developer/generations` · `mode: text-to-video` · **no images (sending one is a 400)**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"seedance_2.5"` |
| `prompt` | `string` | yes | — |
| `mode` | `string` | no | `"text-to-video"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `aspect_ratio` | `select` | no | `"9:16"`, `"16:9"`, `"1:1"`, `"3:4"`, `"4:3"`, `"21:9"`; Tỷ lệ |
| `duration` | `select` | no | `5`, `10`, `15`, `20`, `25`, `30`; default `5`; Thời lượng (giây) |
| `count` | `integer` | no | range `1–8`; default `1` |

Request:

```json
{
    "model": "seedance_2.5",
    "prompt": "A cinematic sunrise over the sea",
    "mode": "text-to-video",
    "aspect_ratio": "9:16",
    "duration": 5
}
```

Response:

```json
{
    "success": true,
    "status": 202,
    "message": null,
    "data": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "queued",
        "is_final": false,
        "model": "seedance_2.5",
        "mode": "text-to-video",
        "message": "Accepted. Generation is running. Poll next.url until is_final is true; do not resend this request.",
        "next": {
            "action": "poll",
            "url": "https://seedvis.com/api/v1/developer/generations/REQUEST_ID?wait=60",
            "after_seconds": 10
        },
        "outputs": [],
        "references": []
    },
    "_then_after_polling": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "completed",
        "is_final": true,
        "model": "seedance_2.5",
        "mode": "text-to-video",
        "message": "Completed.",
        "next": {
            "action": "done"
        },
        "outputs": [
            {
                "type": "video",
                "url": "https://cdn.seedvis.com/result.mp4"
            }
        ],
        "references": []
    }
}
```

Full URL: `https://seedvis.com/api/v1/developer/generations`

#### Seedance 2.5 — image-to-video

`POST /developer/generations` · `mode: image-to-video` · **1–10 images: reference_images**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"seedance_2.5"` |
| `prompt` | `string` | yes | — |
| `reference_images` | `image[] (URL or base64)` | yes | range `1–10`; 1–10 images, URLs and base64 may be mixed. Aliases: reference_images, images, image_url. |
| `reference_images[].file_name` | `string` | no | Optional. Only for base64 images: send the image as {"data": "<base64>", "file_name": "photo.png"} and the stored reference URL keeps that name (…/references/{user}/photo.png, then photo-1.png, photo-2.png for repeats). Without file_name a base64 image gets a random name. Image URLs and multipart files keep their own name. |
| `mode` | `string` | no | `"image-to-video"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `aspect_ratio` | `select` | no | `"9:16"`, `"16:9"`, `"1:1"`, `"3:4"`, `"4:3"`, `"21:9"`; Tỷ lệ |
| `duration` | `select` | no | `5`, `10`, `15`, `20`, `25`, `30`; default `5`; Thời lượng (giây) |
| `count` | `integer` | no | range `1–8`; default `1` |

Request:

```json
{
    "model": "seedance_2.5",
    "prompt": "A cinematic sunrise over the sea",
    "mode": "image-to-video",
    "reference_images": [
        "https://cdn.seedvis.com/reference.png",
        {
            "data": "iVBORw0KGgo…",
            "file_name": "photo.png"
        }
    ],
    "aspect_ratio": "9:16",
    "duration": 5
}
```

Response:

```json
{
    "success": true,
    "status": 202,
    "message": null,
    "data": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "queued",
        "is_final": false,
        "model": "seedance_2.5",
        "mode": "image-to-video",
        "message": "Accepted. Generation is running. Poll next.url until is_final is true; do not resend this request.",
        "next": {
            "action": "poll",
            "url": "https://seedvis.com/api/v1/developer/generations/REQUEST_ID?wait=60",
            "after_seconds": 10
        },
        "outputs": [],
        "references": [
            {
                "field": "reference_images",
                "index": 0,
                "role": "start",
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    },
    "_then_after_polling": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "completed",
        "is_final": true,
        "model": "seedance_2.5",
        "mode": "image-to-video",
        "message": "Completed.",
        "next": {
            "action": "done"
        },
        "outputs": [
            {
                "type": "video",
                "url": "https://cdn.seedvis.com/result.mp4"
            }
        ],
        "references": [
            {
                "field": "reference_images",
                "index": 0,
                "role": "start",
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    }
}
```

Full URL: `https://seedvis.com/api/v1/developer/generations`

#### Seedance 2.0 fast — text-to-video

`POST /developer/generations` · `mode: text-to-video` · **no images (sending one is a 400)**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"seedance_2.0_fast"` |
| `prompt` | `string` | yes | — |
| `mode` | `string` | no | `"text-to-video"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `aspect_ratio` | `select` | no | `"9:16"`, `"16:9"`, `"1:1"`, `"3:4"`, `"4:3"`, `"21:9"`; Tỷ lệ |
| `duration` | `select` | no | `5`, `10`, `15`; default `5`; Thời lượng (giây) |
| `count` | `integer` | no | range `1–8`; default `1` |

Request:

```json
{
    "model": "seedance_2.0_fast",
    "prompt": "A cinematic sunrise over the sea",
    "mode": "text-to-video",
    "aspect_ratio": "9:16",
    "duration": 5
}
```

Response:

```json
{
    "success": true,
    "status": 202,
    "message": null,
    "data": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "queued",
        "is_final": false,
        "model": "seedance_2.0_fast",
        "mode": "text-to-video",
        "message": "Accepted. Generation is running. Poll next.url until is_final is true; do not resend this request.",
        "next": {
            "action": "poll",
            "url": "https://seedvis.com/api/v1/developer/generations/REQUEST_ID?wait=60",
            "after_seconds": 10
        },
        "outputs": [],
        "references": []
    },
    "_then_after_polling": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "completed",
        "is_final": true,
        "model": "seedance_2.0_fast",
        "mode": "text-to-video",
        "message": "Completed.",
        "next": {
            "action": "done"
        },
        "outputs": [
            {
                "type": "video",
                "url": "https://cdn.seedvis.com/result.mp4"
            }
        ],
        "references": []
    }
}
```

Full URL: `https://seedvis.com/api/v1/developer/generations`

#### Seedance 2.0 fast — image-to-video

`POST /developer/generations` · `mode: image-to-video` · **1–10 images: reference_images**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"seedance_2.0_fast"` |
| `prompt` | `string` | yes | — |
| `reference_images` | `image[] (URL or base64)` | yes | range `1–10`; 1–10 images, URLs and base64 may be mixed. Aliases: reference_images, images, image_url. |
| `reference_images[].file_name` | `string` | no | Optional. Only for base64 images: send the image as {"data": "<base64>", "file_name": "photo.png"} and the stored reference URL keeps that name (…/references/{user}/photo.png, then photo-1.png, photo-2.png for repeats). Without file_name a base64 image gets a random name. Image URLs and multipart files keep their own name. |
| `mode` | `string` | no | `"image-to-video"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `aspect_ratio` | `select` | no | `"9:16"`, `"16:9"`, `"1:1"`, `"3:4"`, `"4:3"`, `"21:9"`; Tỷ lệ |
| `duration` | `select` | no | `5`, `10`, `15`; default `5`; Thời lượng (giây) |
| `count` | `integer` | no | range `1–8`; default `1` |

Request:

```json
{
    "model": "seedance_2.0_fast",
    "prompt": "A cinematic sunrise over the sea",
    "mode": "image-to-video",
    "reference_images": [
        "https://cdn.seedvis.com/reference.png",
        {
            "data": "iVBORw0KGgo…",
            "file_name": "photo.png"
        }
    ],
    "aspect_ratio": "9:16",
    "duration": 5
}
```

Response:

```json
{
    "success": true,
    "status": 202,
    "message": null,
    "data": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "queued",
        "is_final": false,
        "model": "seedance_2.0_fast",
        "mode": "image-to-video",
        "message": "Accepted. Generation is running. Poll next.url until is_final is true; do not resend this request.",
        "next": {
            "action": "poll",
            "url": "https://seedvis.com/api/v1/developer/generations/REQUEST_ID?wait=60",
            "after_seconds": 10
        },
        "outputs": [],
        "references": [
            {
                "field": "reference_images",
                "index": 0,
                "role": "start",
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    },
    "_then_after_polling": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "completed",
        "is_final": true,
        "model": "seedance_2.0_fast",
        "mode": "image-to-video",
        "message": "Completed.",
        "next": {
            "action": "done"
        },
        "outputs": [
            {
                "type": "video",
                "url": "https://cdn.seedvis.com/result.mp4"
            }
        ],
        "references": [
            {
                "field": "reference_images",
                "index": 0,
                "role": "start",
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    }
}
```

Full URL: `https://seedvis.com/api/v1/developer/generations`

### Google Veo 3.1

Model id: `Veo-3.1`

> Google Veo shape also works: `POST /google/v1beta/models/Veo-3.1:predictLongRunning` with `instances[0].image` / `lastFrame` / `referenceImages`; the mode is inferred the same way. On the web UI this model appears as Frames and Ingredients.

#### Google Veo 3.1 — text-to-video

`POST /developer/generations` · `mode: text-to-video` · **no images (sending one is a 400)**
Also: `POST /google/v1beta/models/Veo-3.1:predictLongRunning`

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"Veo-3.1"` |
| `prompt` | `string` | yes | — |
| `mode` | `string` | no | `"text-to-video"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`; default `"9:16"`; Aspect ratio |
| `count` | `number` | no | range `1–4`; default `1`; Count |
| `duration` | `select` | no | `"4s"`, `"6s"`, `"8s"`; default `"8s"`; Duration |
| `upscale_video` | `select` | no | `"none"`, `"1080p"`; default `"none"`; Upscale |

Request:

```json
{
    "model": "Veo-3.1",
    "prompt": "A cinematic sunrise over the sea",
    "mode": "text-to-video",
    "aspect_ratio": "9:16",
    "count": 1,
    "duration": "8s",
    "upscale_video": "none"
}
```

Response:

```json
{
    "success": true,
    "status": 202,
    "message": null,
    "data": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "queued",
        "is_final": false,
        "model": "Veo-3.1",
        "mode": "text-to-video",
        "message": "Accepted. Generation is running. Poll next.url until is_final is true; do not resend this request.",
        "next": {
            "action": "poll",
            "url": "https://seedvis.com/api/v1/developer/generations/REQUEST_ID?wait=60",
            "after_seconds": 10
        },
        "outputs": [],
        "references": []
    },
    "_then_after_polling": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "completed",
        "is_final": true,
        "model": "Veo-3.1",
        "mode": "text-to-video",
        "message": "Completed.",
        "next": {
            "action": "done"
        },
        "outputs": [
            {
                "type": "video",
                "url": "https://cdn.seedvis.com/result.mp4"
            }
        ],
        "references": []
    }
}
```

Full URL: `https://seedvis.com/api/v1/developer/generations`

#### Google Veo 3.1 — image-to-video

`POST /developer/generations` · `mode: image-to-video` · **exactly 1 image: image**
Also: `POST /google/v1beta/models/Veo-3.1:predictLongRunning`

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"Veo-3.1"` |
| `prompt` | `string` | yes | — |
| `image` | `image (URL or base64)` | yes | Exactly one image. Aliases: reference_images, images, image_url. |
| `image.file_name` | `string` | no | Optional. Only for base64 images: send the image as {"data": "<base64>", "file_name": "photo.png"} and the stored reference URL keeps that name (…/references/{user}/photo.png, then photo-1.png, photo-2.png for repeats). Without file_name a base64 image gets a random name. Image URLs and multipart files keep their own name. |
| `mode` | `string` | no | `"image-to-video"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`; default `"9:16"`; Aspect ratio |
| `count` | `number` | no | range `1–4`; default `1`; Count |
| `duration` | `select` | no | `"4s"`, `"6s"`, `"8s"`; default `"8s"`; Duration |
| `upscale_video` | `select` | no | `"none"`, `"1080p"`; default `"none"`; Upscale |

Request:

```json
{
    "model": "Veo-3.1",
    "prompt": "A cinematic sunrise over the sea",
    "mode": "image-to-video",
    "image": {
        "data": "iVBORw0KGgo…",
        "file_name": "photo.png"
    },
    "aspect_ratio": "9:16",
    "count": 1,
    "duration": "8s",
    "upscale_video": "none"
}
```

Response:

```json
{
    "success": true,
    "status": 202,
    "message": null,
    "data": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "queued",
        "is_final": false,
        "model": "Veo-3.1",
        "mode": "image-to-video",
        "message": "Accepted. Generation is running. Poll next.url until is_final is true; do not resend this request.",
        "next": {
            "action": "poll",
            "url": "https://seedvis.com/api/v1/developer/generations/REQUEST_ID?wait=60",
            "after_seconds": 10
        },
        "outputs": [],
        "references": [
            {
                "field": "image",
                "index": 0,
                "role": "start",
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    },
    "_then_after_polling": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "completed",
        "is_final": true,
        "model": "Veo-3.1",
        "mode": "image-to-video",
        "message": "Completed.",
        "next": {
            "action": "done"
        },
        "outputs": [
            {
                "type": "video",
                "url": "https://cdn.seedvis.com/result.mp4"
            }
        ],
        "references": [
            {
                "field": "image",
                "index": 0,
                "role": "start",
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    }
}
```

Full URL: `https://seedvis.com/api/v1/developer/generations`

#### Google Veo 3.1 — multi-image-to-video

`POST /developer/generations` · `mode: multi-image-to-video` · **1–3 images: referenceImages**
Also: `POST /google/v1beta/models/Veo-3.1:predictLongRunning`

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"Veo-3.1"` |
| `prompt` | `string` | yes | — |
| `referenceImages` | `image[] (URL or base64)` | yes | range `1–3`; 1–3 images, URLs and base64 may be mixed. Aliases: reference_images, images, image_url. |
| `referenceImages[].file_name` | `string` | no | Optional. Only for base64 images: send the image as {"data": "<base64>", "file_name": "photo.png"} and the stored reference URL keeps that name (…/references/{user}/photo.png, then photo-1.png, photo-2.png for repeats). Without file_name a base64 image gets a random name. Image URLs and multipart files keep their own name. |
| `mode` | `string` | no | `"multi-image-to-video"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`; default `"9:16"`; Aspect ratio |
| `count` | `number` | no | range `1–4`; default `1`; Count |
| `duration` | `select` | no | `"4s"`, `"6s"`, `"8s"`; default `"8s"`; Duration |
| `upscale_video` | `select` | no | `"none"`, `"1080p"`; default `"none"`; Upscale |

Request:

```json
{
    "model": "Veo-3.1",
    "prompt": "A cinematic sunrise over the sea",
    "mode": "multi-image-to-video",
    "referenceImages": [
        "https://cdn.seedvis.com/reference.png",
        {
            "data": "iVBORw0KGgo…",
            "file_name": "photo.png"
        }
    ],
    "aspect_ratio": "9:16",
    "count": 1,
    "duration": "8s",
    "upscale_video": "none"
}
```

Response:

```json
{
    "success": true,
    "status": 202,
    "message": null,
    "data": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "queued",
        "is_final": false,
        "model": "Veo-3.1",
        "mode": "multi-image-to-video",
        "message": "Accepted. Generation is running. Poll next.url until is_final is true; do not resend this request.",
        "next": {
            "action": "poll",
            "url": "https://seedvis.com/api/v1/developer/generations/REQUEST_ID?wait=60",
            "after_seconds": 10
        },
        "outputs": [],
        "references": [
            {
                "field": "referenceImages",
                "index": 0,
                "role": null,
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    },
    "_then_after_polling": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "completed",
        "is_final": true,
        "model": "Veo-3.1",
        "mode": "multi-image-to-video",
        "message": "Completed.",
        "next": {
            "action": "done"
        },
        "outputs": [
            {
                "type": "video",
                "url": "https://cdn.seedvis.com/result.mp4"
            }
        ],
        "references": [
            {
                "field": "referenceImages",
                "index": 0,
                "role": null,
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    }
}
```

Full URL: `https://seedvis.com/api/v1/developer/generations`

#### Google Veo 3.1 — batch-frame

`POST /developer/generations` · `mode: batch-frame` · **exactly 2 images: image + lastFrame**
Also: `POST /google/v1beta/models/Veo-3.1:predictLongRunning`

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"Veo-3.1"` |
| `prompt` | `string` | yes | — |
| `image` | `image (URL or base64)` | yes | Start frame. Alias: start_image. |
| `image.file_name` | `string` | no | Optional. Only for base64 images: send the image as {"data": "<base64>", "file_name": "photo.png"} and the stored reference URL keeps that name (…/references/{user}/photo.png, then photo-1.png, photo-2.png for repeats). Without file_name a base64 image gets a random name. Image URLs and multipart files keep their own name. |
| `lastFrame` | `image (URL or base64)` | yes | End frame. Alias: end_image. |
| `lastFrame.file_name` | `string` | no | Optional. Only for base64 images: send the image as {"data": "<base64>", "file_name": "photo.png"} and the stored reference URL keeps that name (…/references/{user}/photo.png, then photo-1.png, photo-2.png for repeats). Without file_name a base64 image gets a random name. Image URLs and multipart files keep their own name. |
| `mode` | `string` | no | `"batch-frame"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`; default `"9:16"`; Aspect ratio |
| `count` | `number` | no | range `1–4`; default `1`; Count |
| `duration` | `select` | no | `"4s"`, `"6s"`, `"8s"`; default `"8s"`; Duration |
| `upscale_video` | `select` | no | `"none"`, `"1080p"`; default `"none"`; Upscale |

Request:

```json
{
    "model": "Veo-3.1",
    "prompt": "A cinematic product photo",
    "mode": "batch-frame",
    "image": "https://cdn.seedvis.com/reference.png",
    "lastFrame": {
        "data": "iVBORw0KGgo…",
        "file_name": "last-frame.png"
    },
    "aspect_ratio": "9:16",
    "count": 1,
    "duration": "8s",
    "upscale_video": "none"
}
```

Response:

```json
{
    "success": true,
    "status": 202,
    "message": null,
    "data": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "queued",
        "is_final": false,
        "model": "Veo-3.1",
        "mode": "batch-frame",
        "message": "Accepted. Generation is running. Poll next.url until is_final is true; do not resend this request.",
        "next": {
            "action": "poll",
            "url": "https://seedvis.com/api/v1/developer/generations/REQUEST_ID?wait=60",
            "after_seconds": 10
        },
        "outputs": [],
        "references": [
            {
                "field": "image",
                "index": 0,
                "role": "start",
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    },
    "_then_after_polling": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "completed",
        "is_final": true,
        "model": "Veo-3.1",
        "mode": "batch-frame",
        "message": "Completed.",
        "next": {
            "action": "done"
        },
        "outputs": [
            {
                "type": "video",
                "url": "https://cdn.seedvis.com/result.mp4"
            }
        ],
        "references": [
            {
                "field": "image",
                "index": 0,
                "role": "start",
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    }
}
```

Full URL: `https://seedvis.com/api/v1/developer/generations`

### Omni Flash

Model id: `Omni-Flash`

#### Omni Flash — text-to-video

`POST /developer/generations` · `mode: text-to-video` · **no images (sending one is a 400)**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"Omni-Flash"` |
| `prompt` | `string` | yes | — |
| `mode` | `string` | no | `"text-to-video"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`; default `"16:9"`; Tỉ lệ khung |
| `count` | `number` | no | range `1–4`; default `1`; Số video |

Request:

```json
{
    "model": "Omni-Flash",
    "prompt": "A cinematic sunrise over the sea",
    "mode": "text-to-video",
    "aspect_ratio": "16:9",
    "count": 1
}
```

Response:

```json
{
    "success": true,
    "status": 202,
    "message": null,
    "data": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "queued",
        "is_final": false,
        "model": "Omni-Flash",
        "mode": "text-to-video",
        "message": "Accepted. Generation is running. Poll next.url until is_final is true; do not resend this request.",
        "next": {
            "action": "poll",
            "url": "https://seedvis.com/api/v1/developer/generations/REQUEST_ID?wait=60",
            "after_seconds": 10
        },
        "outputs": [],
        "references": []
    },
    "_then_after_polling": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "completed",
        "is_final": true,
        "model": "Omni-Flash",
        "mode": "text-to-video",
        "message": "Completed.",
        "next": {
            "action": "done"
        },
        "outputs": [
            {
                "type": "video",
                "url": "https://cdn.seedvis.com/result.mp4"
            }
        ],
        "references": []
    }
}
```

Full URL: `https://seedvis.com/api/v1/developer/generations`

#### Omni Flash — image-to-video

`POST /developer/generations` · `mode: image-to-video` · **exactly 1 image: image**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"Omni-Flash"` |
| `prompt` | `string` | yes | — |
| `image` | `image (URL or base64)` | yes | Exactly one image. Aliases: reference_images, images, image_url. |
| `image.file_name` | `string` | no | Optional. Only for base64 images: send the image as {"data": "<base64>", "file_name": "photo.png"} and the stored reference URL keeps that name (…/references/{user}/photo.png, then photo-1.png, photo-2.png for repeats). Without file_name a base64 image gets a random name. Image URLs and multipart files keep their own name. |
| `mode` | `string` | no | `"image-to-video"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`; default `"16:9"`; Tỉ lệ khung |
| `count` | `number` | no | range `1–4`; default `1`; Số video |

Request:

```json
{
    "model": "Omni-Flash",
    "prompt": "A cinematic sunrise over the sea",
    "mode": "image-to-video",
    "image": {
        "data": "iVBORw0KGgo…",
        "file_name": "photo.png"
    },
    "aspect_ratio": "16:9",
    "count": 1
}
```

Response:

```json
{
    "success": true,
    "status": 202,
    "message": null,
    "data": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "queued",
        "is_final": false,
        "model": "Omni-Flash",
        "mode": "image-to-video",
        "message": "Accepted. Generation is running. Poll next.url until is_final is true; do not resend this request.",
        "next": {
            "action": "poll",
            "url": "https://seedvis.com/api/v1/developer/generations/REQUEST_ID?wait=60",
            "after_seconds": 10
        },
        "outputs": [],
        "references": [
            {
                "field": "image",
                "index": 0,
                "role": "start",
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    },
    "_then_after_polling": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "completed",
        "is_final": true,
        "model": "Omni-Flash",
        "mode": "image-to-video",
        "message": "Completed.",
        "next": {
            "action": "done"
        },
        "outputs": [
            {
                "type": "video",
                "url": "https://cdn.seedvis.com/result.mp4"
            }
        ],
        "references": [
            {
                "field": "image",
                "index": 0,
                "role": "start",
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    }
}
```

Full URL: `https://seedvis.com/api/v1/developer/generations`

#### Omni Flash — multi-image-to-video

`POST /developer/generations` · `mode: multi-image-to-video` · **1–3 images: images**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"Omni-Flash"` |
| `prompt` | `string` | yes | — |
| `images` | `image[] (URL or base64)` | yes | range `1–3`; 1–3 images, URLs and base64 may be mixed. Aliases: reference_images, images, image_url. |
| `images[].file_name` | `string` | no | Optional. Only for base64 images: send the image as {"data": "<base64>", "file_name": "photo.png"} and the stored reference URL keeps that name (…/references/{user}/photo.png, then photo-1.png, photo-2.png for repeats). Without file_name a base64 image gets a random name. Image URLs and multipart files keep their own name. |
| `mode` | `string` | no | `"multi-image-to-video"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`; default `"16:9"`; Tỉ lệ khung |
| `count` | `number` | no | range `1–4`; default `1`; Số video |

Request:

```json
{
    "model": "Omni-Flash",
    "prompt": "A cinematic sunrise over the sea",
    "mode": "multi-image-to-video",
    "images": [
        "https://cdn.seedvis.com/reference.png",
        {
            "data": "iVBORw0KGgo…",
            "file_name": "photo.png"
        }
    ],
    "aspect_ratio": "16:9",
    "count": 1
}
```

Response:

```json
{
    "success": true,
    "status": 202,
    "message": null,
    "data": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "queued",
        "is_final": false,
        "model": "Omni-Flash",
        "mode": "multi-image-to-video",
        "message": "Accepted. Generation is running. Poll next.url until is_final is true; do not resend this request.",
        "next": {
            "action": "poll",
            "url": "https://seedvis.com/api/v1/developer/generations/REQUEST_ID?wait=60",
            "after_seconds": 10
        },
        "outputs": [],
        "references": [
            {
                "field": "images",
                "index": 0,
                "role": null,
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    },
    "_then_after_polling": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "completed",
        "is_final": true,
        "model": "Omni-Flash",
        "mode": "multi-image-to-video",
        "message": "Completed.",
        "next": {
            "action": "done"
        },
        "outputs": [
            {
                "type": "video",
                "url": "https://cdn.seedvis.com/result.mp4"
            }
        ],
        "references": [
            {
                "field": "images",
                "index": 0,
                "role": null,
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    }
}
```

Full URL: `https://seedvis.com/api/v1/developer/generations`

#### Omni Flash — video-to-video

`POST /developer/generations` · `mode: video-to-video` · **1 video (required): video + 0–3 images: images**

| Parameter | Type | Required | Values / default |
|---|---|:---:|---|
| `model` | `string` | yes | `"Omni-Flash"` |
| `prompt` | `string` | yes | — |
| `images` | `image[] (URL or base64)` | no | range `0–3`; 0–3 images, URLs and base64 may be mixed. Aliases: reference_images, images, image_url. |
| `images[].file_name` | `string` | no | Optional. Only for base64 images: send the image as {"data": "<base64>", "file_name": "photo.png"} and the stored reference URL keeps that name (…/references/{user}/photo.png, then photo-1.png, photo-2.png for repeats). Without file_name a base64 image gets a random name. Image URLs and multipart files keep their own name. |
| `video` | `video (URL or base64)` | yes | Source video for video-to-video. Public MP4, MOV or WebM URL, or base64 (data:video/mp4;base64,…). Max 100 MiB. |
| `mode` | `string` | no | `"video-to-video"`; Optional. Inferred from the images you send; set it to be explicit — a mismatch is rejected with 400. |
| `aspect_ratio` | `select` | no | `"16:9"`, `"9:16"`; default `"16:9"`; Tỉ lệ khung |
| `count` | `number` | no | range `1–4`; default `1`; Số video |

Request:

```json
{
    "model": "Omni-Flash",
    "prompt": "A cinematic sunrise over the sea",
    "mode": "video-to-video",
    "video": "https://cdn.seedvis.com/source.mp4",
    "images": [
        "https://cdn.seedvis.com/reference.png",
        {
            "data": "iVBORw0KGgo…",
            "file_name": "photo.png"
        }
    ],
    "aspect_ratio": "16:9",
    "count": 1
}
```

Response:

```json
{
    "success": true,
    "status": 202,
    "message": null,
    "data": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "queued",
        "is_final": false,
        "model": "Omni-Flash",
        "mode": "video-to-video",
        "message": "Accepted. Generation is running. Poll next.url until is_final is true; do not resend this request.",
        "next": {
            "action": "poll",
            "url": "https://seedvis.com/api/v1/developer/generations/REQUEST_ID?wait=60",
            "after_seconds": 10
        },
        "outputs": [],
        "references": [
            {
                "field": "images",
                "index": 0,
                "role": null,
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    },
    "_then_after_polling": {
        "id": "REQUEST_ID",
        "object": "generation",
        "status": "completed",
        "is_final": true,
        "model": "Omni-Flash",
        "mode": "video-to-video",
        "message": "Completed.",
        "next": {
            "action": "done"
        },
        "outputs": [
            {
                "type": "video",
                "url": "https://cdn.seedvis.com/result.mp4"
            }
        ],
        "references": [
            {
                "field": "images",
                "index": 0,
                "role": null,
                "source": "url",
                "url": "https://cdn.seedvis.com/references/…png"
            }
        ]
    }
}
```

Full URL: `https://seedvis.com/api/v1/developer/generations`

## Use with an AI agent

Give Claude, ChatGPT, Cursor or any coding agent this URL — it contains every model, mode and example:

`https://seedvis.com/api/v1/developer-api/docs.md`

Example prompt: `Read https://seedvis.com/api/v1/developer-api/docs.md and write the Seedvis integration code. Copy the client from "Copy this client".`

### MCP server

```bash
# Claude Code — the --header flag goes after the URL
claude mcp add --transport http seedvis https://seedvis.com/api/v1/mcp --header "Authorization: Bearer YOUR_API_KEY"
```

Cursor / VS Code (`~/.cursor/mcp.json`, or `.vscode/mcp.json` under a `servers` key):

```json
{
    "mcpServers": {
        "seedvis": {
            "url": "https://seedvis.com/api/v1/mcp",
            "headers": {
                "Authorization": "Bearer YOUR_API_KEY"
            }
        }
    }
}
```

Claude Desktop / ChatGPT (custom connector, no header support) — put the key in the URL and treat that URL as a secret:

```text
https://seedvis.com/api/v1/mcp/YOUR_API_KEY
```

Tools: `seedvis_list_models`, `seedvis_generate` (with `reference_images` as URLs or base64 — `{"data", "file_name"}` keeps the file name — and an optional `mode`), `seedvis_get_generation`, account info and usage. Keep the API key secret.

## Account

- `GET /account/info`: plan, API entitlement, balance, rate/concurrency/queue limits.
- `GET /account/usage`: requests today, this month, total, counts by status, and balance.

## Webhooks (optional)

The API works without a webhook. Configure one in the Seedvis API settings to receive `generation.completed` and `generation.failed`.

Verify `X-Seedvis-Signature` as `HMAC_SHA256(secret, timestamp + "." + raw_body)` using `X-Seedvis-Timestamp`.

Return any `2xx` response quickly. Failed deliveries are retried automatically.

## Errors

| HTTP | Code | Meaning |
|---:|---|---|
| 400 | `invalid_value` | Invalid request or parameter value |
| 400 | `invalid_image` | A reference image is not a public URL, data URL or base64 image; `errors["field[i]"]` names it |
| 400 / 422 | `image_rule` | Wrong number of images for the mode; the message names the mode that fits |
| 401 | `unauthorized` | Missing or invalid API key |
| 402 | `insufficient_credits` | Insufficient credit balance |
| 403 | `forbidden` | Package or key lacks access |
| 404 | `model_not_found` | Unknown model id (the message lists the valid ids), or a model that is not open yet — the message names its status |
| 503 | `model_maintenance` | The model exists but is under maintenance; retry later |
| 409 | `idempotency_conflict` | Same `Idempotency-Key`, different body |
| 422 | `validation_error` | Input violates the model schema, or the concurrency + queue limit of your plan is reached |
| 429 | `rate_limit_exceeded` | Retry after the `Retry-After` delay |
| 500 | `server_error` | Temporary Seedvis error |
| 502 | `generation_failed` | Provider generation failed |

Native endpoint (`/developer/generations`):

```json
{
    "success": false,
    "status": 400,
    "code": "invalid_image",
    "message": "Reference image reference_images[1] is not usable: …",
    "errors": {
        "reference_images[1]": [
            "Reference image reference_images[1] is not usable: …"
        ]
    }
}
```

OpenAI-compatible endpoints:

```json
{
    "error": {
        "message": "Invalid model.",
        "type": "invalid_request_error",
        "code": "model_not_found",
        "param": "model"
    }
}
```

Google-compatible endpoints:

```json
{
    "error": {
        "code": 404,
        "message": "Model not found.",
        "status": "NOT_FOUND"
    }
}
```

Only retry `429` and `5xx` responses, with the same `Idempotency-Key`. Use exponential backoff and honor `Retry-After`.
