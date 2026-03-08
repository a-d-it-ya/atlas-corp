# ATLAS OS

Defense C2 system — Army + Naval theater.

## Local dev
```bash
pip install -r requirements.txt
python server.py
# open http://localhost:8000
```

## Deploy (Railway)
1. Push to GitHub
2. New project on railway.app → Deploy from GitHub repo
3. Done — Railway auto-detects Python and uses Procfile
