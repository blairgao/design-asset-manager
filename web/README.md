# Web client

React + TypeScript single-page app (ADR-012). Talks to the API with an `X-Firm-Id` header.
There is no sign-in yet: the API answers `/me` with a fixed local user.

```sh
cd web
npm install
cp .env.example .env.local   # set VITE_API_BASE if the API is not on localhost:8000
npm run dev                  # http://localhost:5173
npm run build                # static bundle in dist/
```

The API must allow this origin (`DAM_WEB_ORIGIN`), so run both on the hosts configured in
the API's `.env`.
