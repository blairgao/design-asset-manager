# Web client

React + TypeScript single-page app (ADR-012). Talks to the API with cookie sessions and an
`X-Firm-Id` header.

```sh
cd web
npm install
cp .env.example .env.local   # set VITE_API_BASE if the API is not on localhost:8000
npm run dev                  # http://localhost:5173
npm run build                # static bundle in dist/
```

The API must allow this origin (`DAM_WEB_ORIGIN`) and the magic-link redirect lands on this
origin, so run both on the hosts configured in the API's `.env`.
