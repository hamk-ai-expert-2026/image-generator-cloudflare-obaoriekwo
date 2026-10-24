"""Web-based AI image generator (Streamlit + Cloudflare Workers AI).

Run with:  python -m streamlit run app.py
"""
import base64
import os
import random
from datetime import datetime

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)

ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "").strip()
API_TOKEN = os.getenv("CF_API_TOKEN", "").strip()
API_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
TIMEOUT_S = 120
MAX_PROMPT_CHARS = 1000

# Models and the options each one supports.
MODELS = {
    "Stable Diffusion XL (all options)": {
        "id": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
        "sizes": True, "negative": True, "seed": True,
        "steps_key": "num_steps", "steps": (5, 20, 15),  # min, max, default
    },
    "FLUX.1 schnell (fast, square only)": {
        "id": "@cf/black-forest-labs/flux-1-schnell",
        "sizes": False, "negative": False, "seed": False,
        "steps_key": "steps", "steps": (1, 8, 4),
    },
}

# Aspect ratio -> (width, height); multiples of 64 work well for SDXL.
ASPECT_RATIOS = {
    "Square 1:1": (1024, 1024),
    "Landscape 16:9": (1024, 576),
    "Portrait 9:16": (576, 1024),
    "Landscape 4:3": (1024, 768),
    "Portrait 3:4": (768, 1024),
}


class ImageAPIError(Exception):
    """An error with a message that is safe and useful to show the user."""


# ---------- API call ----------

def api_message(resp):
    """Pull Cloudflare's own error text out of a response, if there is any."""
    try:
        errs = resp.json().get("errors") or []
        return "; ".join(e.get("message", "") for e in errs if e.get("message"))
    except ValueError:
        return resp.text[:200]


def generate_image(model_cfg, prompt, steps, width, height, negative, seed):
    """Call Cloudflare Workers AI once and return the image bytes."""
    payload = {"prompt": prompt, model_cfg["steps_key"]: steps}
    if model_cfg["sizes"]:
        payload.update(width=width, height=height)
    if model_cfg["negative"] and negative:
        payload["negative_prompt"] = negative
    if model_cfg["seed"]:
        payload["seed"] = seed

    url = API_URL.format(account=ACCOUNT_ID, model=model_cfg["id"])
    try:
        resp = requests.post(url, headers={"Authorization": f"Bearer {API_TOKEN}"},
                             json=payload, timeout=TIMEOUT_S)
    except requests.Timeout:
        raise ImageAPIError("The request timed out. The service may be busy; try again in a minute.")
    except requests.ConnectionError:
        raise ImageAPIError("Could not reach Cloudflare. Check your internet connection.")

    if resp.status_code != 200:
        detail = api_message(resp)
        hints = {
            400: "The request was rejected (400). Try a different prompt or settings.",
            401: "Your API token was rejected (401). Check CF_API_TOKEN in the .env file.",
            403: "Access denied (403). Make sure the token has 'Workers AI' permission and CF_ACCOUNT_ID is correct.",
            404: "Not found (404). Check CF_ACCOUNT_ID in the .env file.",
            429: "Rate or daily free limit reached (429). Wait a bit, or try again tomorrow.",
        }
        msg = hints.get(resp.status_code) or f"The image service had a problem ({resp.status_code})."
        raise ImageAPIError(f"{msg} Details: {detail}" if detail else msg)

    # SDXL returns raw PNG bytes; FLUX returns JSON with a base64 image.
    if resp.headers.get("content-type", "").startswith("application/json"):
        try:
            data = resp.json()
            image_b64 = data["result"]["image"]
            return base64.b64decode(image_b64)
        except (ValueError, KeyError, TypeError):
            raise ImageAPIError(f"The service returned no image. Details: {api_message(resp)}")
    if not resp.content:
        raise ImageAPIError("The service returned an empty image. Try again.")
    return resp.content


def image_type(data):
    """Return (extension, mime type) by looking at the file's first bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    return "jpg", "image/jpeg"


# ---------- Page ----------

st.set_page_config(page_title="AI Image Generator", page_icon="🎨", layout="centered")
st.title("🎨 AI Image Generator")
st.caption("Powered by Cloudflare Workers AI")

if "images" not in st.session_state:
    st.session_state.images = []  # list of dicts: {data, seed, model}

configured = bool(ACCOUNT_ID and API_TOKEN)
if not configured:
    st.error("CF_ACCOUNT_ID or CF_API_TOKEN is missing. Copy .env.example to .env, fill both in, and restart.")

# The model picker sits outside the form so the options below update immediately.
model_name = st.selectbox("Model", list(MODELS))
cfg = MODELS[model_name]

with st.form("generate"):
    prompt = st.text_area(
        "Prompt",
        placeholder="A cozy wooden cabin in a snowy forest at dusk, warm light in the windows",
        max_chars=MAX_PROMPT_CHARS,
        height=100,
    )
    negative = ""
    if cfg["negative"]:
        negative = st.text_input("Negative prompt (optional)",
                                 placeholder="blurry, low quality, text, watermark")

    col1, col2 = st.columns(2)
    with col1:
        if cfg["sizes"]:
            aspect = st.selectbox("Aspect ratio", list(ASPECT_RATIOS))
        else:
            aspect = "Square 1:1"
            st.selectbox("Aspect ratio", ["Square 1:1 (fixed for this model)"], disabled=True)
        count = st.slider("Number of images", 1, 4, 1)
    with col2:
        lo, hi, default = cfg["steps"]
        steps = st.slider("Quality (inference steps)", lo, hi, default,
                          help="More steps = more detail but slower and uses more of the free allowance.")
        seed_text = ""
        if cfg["seed"]:
            seed_text = st.text_input("Seed (optional)", placeholder="random",
                                      help="Use the same seed and prompt to get the same image again.")
    submitted = st.form_submit_button("Generate", type="primary", disabled=not configured)

if submitted:
    prompt = prompt.strip()
    seed_text = seed_text.strip()
    if not prompt:
        st.warning("Please enter a prompt first.")
    elif seed_text and not seed_text.isdigit():
        st.warning("The seed must be a whole number, or left empty.")
    else:
        width, height = ASPECT_RATIOS[aspect]
        base_seed = int(seed_text) if seed_text else random.randint(0, 2**31 - 1)

        new_images = []
        progress = st.progress(0.0, text="Generating…")
        for i in range(count):
            seed = base_seed + i
            try:
                data = generate_image(cfg, prompt, steps, width, height, negative.strip(), seed)
                new_images.append({"data": data, "seed": seed if cfg["seed"] else None,
                                   "model": model_name})
            except ImageAPIError as err:
                st.error(str(err))
                break  # the same error would usually repeat for the rest
            except Exception as err:  # never let anything unexpected crash the page
                st.error(f"Unexpected error: {type(err).__name__}: {err}")
                break
            progress.progress((i + 1) / count, text=f"Generated {i + 1} of {count}")
        progress.empty()

        if new_images:
            st.session_state.images = new_images

# ---------- Results ----------

images = st.session_state.images
if images:
    st.subheader("Result" if len(images) == 1 else "Results")
    cols = st.columns(min(len(images), 2))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for i, img in enumerate(images):
        ext, mime = image_type(img["data"])
        caption = img["model"] + (f" · seed {img['seed']}" if img["seed"] is not None else "")
        with cols[i % len(cols)]:
            st.image(img["data"], caption=caption, width="stretch")
            st.download_button(
                f"⬇️ Download {ext.upper()}",
                data=img["data"],
                file_name=f"image-{stamp}-{i + 1}.{ext}",
                mime=mime,
                key=f"dl-{i}",
                on_click="ignore",  # downloading doesn't rerun or clear the page
            )
    if st.button("Clear results"):
        st.session_state.images = []
        st.rerun()
