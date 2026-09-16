# NFL Analytics UI

React + TypeScript app for exploring warehouse dimensions. The homepage is a
team dropdown; a logo grid can replace it later without changing the API.

## Run locally

The UI proxies `/api` to the FastAPI read layer on port 8000.

```bash
make api    # terminal 1: FastAPI on http://127.0.0.1:8000
make web    # terminal 2: Vite on http://127.0.0.1:5173
```

First time: `npm --prefix web install`.
