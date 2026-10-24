# AI Image Generator (Assignment #14)

A Streamlit web app that turns a text prompt into images using the **Cloudflare Workers AI** API. The free Workers plan includes a daily allowance, so no payment is needed.

Models:
- **Stable Diffusion XL** (`@cf/stabilityai/stable-diffusion-xl-base-1.0`): aspect ratio, negative prompt, seed, steps
- **FLUX.1 schnell** (`@cf/black-forest-labs/flux-1-schnell`): fast, square images, steps

## Setup

1. Create a free account at https://dash.cloudflare.com.
2. In the dashboard open **AI → Workers AI → Use REST API**:
   - copy your **Account ID**;
   - click **Create a Workers AI API Token**, then copy the token.
3. Install and configure:

```bash
python -m pip install -r requirements.txt
copy .env.example .env      # macOS/Linux: cp .env.example .env
```

4. Put both values into `.env` and save:

```
CF_ACCOUNT_ID=...
CF_API_TOKEN=...
```

## Run

```bash
python -m streamlit run app.py
```

The app opens at http://localhost:8501.

## How it meets the requirements

| Requirement | Where in `app.py` |
|---|---|
| Accepts a text prompt | `st.text_area("Prompt")`; an empty prompt shows a warning instead of calling the API |
| Generation options | **Model**, **aspect ratio** (1:1, 16:9, 9:16, 4:3, 3:4), **number of images** (1–4), **quality** (inference steps), optional **seed** and **negative prompt** (SDXL) |
| Displays the image | `st.image()` in the Results section |
| Download | `st.download_button()` under each image |
| Handles API errors | `generate_image()` raises a readable `ImageAPIError` for a bad token (401), wrong permissions or account ID (403/404), rejected requests (400), rate or daily limit (429), server errors, timeouts, network failures and empty responses, including Cloudflare's own error text. The page never crashes. |

## Testing the error handling

- Leave the `.env` values empty → "CF_ACCOUNT_ID or CF_API_TOKEN is missing".
- Change one character of the token → "Your API token was rejected (401)".
- Change the account ID → a 403/404 message.
- Click Generate with an empty prompt → "Please enter a prompt first".

## Notes

- The free plan includes 10,000 "neurons" per day, enough for many images. It resets daily.
- The token stays in `.env`, which `.gitignore` keeps out of GitHub.
