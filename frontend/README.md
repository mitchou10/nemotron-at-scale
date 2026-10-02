# Frontend

Page de statut des workers ASR : HTML, CSS et JavaScript sans dépendance ni build. Elle interroge
`GET /api/v1/asr/instances` et `GET /api/v1/asr/history` du backend.

nginx (image non privilégiée, port 8080) sert la page et proxifie `/api/` vers `BACKEND_URL`
(`http://backend:8000` par défaut) : le navigateur reste sur une seule origine, sans CORS.

```bash
docker compose up frontend        # http://localhost:3000
```

Développement sans Docker : `python3 -m http.server -d frontend 3000` ne proxifie pas l'API ; lancer plutôt
le service via Compose.
