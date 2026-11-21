# revel8 API explorer

A shareable UI over the revel8 target API, so the team can see what the API does and
talk to it by hand — list scenarios, open a session, send messages on any channel, hold
a live conversation, and read the events that come back.

Each browser session keeps its own API key and target session (nothing shared
server-side), so the link is safe to share; everyone pastes the team key in the
Connection box.

## Gradio (public link — recommended)

`gradio_app.py` launches with `share=True`, which gives a public `*.gradio.live` link
that works from anywhere (good for off-network teammates). The link is temporary (up to
~1 week).

```bash
cd api_explorer
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python gradio_app.py           # prints a local URL + a public https://xxxx.gradio.live
```

Anyone with the link can open the UI; they still need the **team key** (pasted in the
Connection box) to call the API. Nothing is baked in.

## Streamlit (LAN-only alternative)

`app.py` is the same explorer in Streamlit; it serves on the local network only.

```bash
streamlit run app.py --server.address 0.0.0.0     # http://<your-LAN-ip>:8501
```

Optional for either: `export REVEL8_API_KEY=...` before launching to pre-fill the key.
