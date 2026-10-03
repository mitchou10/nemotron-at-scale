# Interface d'administration

Application React (Vite, TypeScript) avec Tailwind CSS et [shadcn/ui](https://ui.shadcn.com), servie par nginx.
Elle interroge `/api/v1/admin/*` du backend (nginx proxifie `/api/` vers `BACKEND_URL`, sans CORS).

| Page | Contenu |
|---|---|
| Vue d'ensemble | état des workers, requêtes TTS (taux de réussite, durée p95, caractères), flux STT (en cours, reprises, échecs, temps d'audio), appels dans le temps, durée des synthèses, voix / formats / workers les plus sollicités |
| Workers | tous les workers enregistrés : état, type, adresse, priorité, charge, latence, dernier signe de vie |
| Transcription | flux récents (client, worker, état, reprises, durée), filtre par état |
| Synthèse vocale | requêtes récentes (code, worker, voix, format, caractères, taille audio, premier octet, durée), filtre par résultat |

La période (1 h, 6 h, 24 h, 7 j, 30 j) se choisit en haut à droite et reste dans l'URL (`?range=7d`) ; les données se
rafraîchissent toutes les 10 s. Thème clair, sombre ou système.

Si le backend a un `ADMIN_TOKEN`, l'interface demande ce jeton (gardé le temps de la session du navigateur).

## Développement

```bash
pnpm install
pnpm dev          # http://localhost:3000, proxifie /api vers http://localhost:8000 (BACKEND_URL pour changer)
pnpm test         # vitest
pnpm lint         # oxlint
pnpm typecheck    # tsc
pnpm build        # dist/
```

Pour avoir des données à regarder sans trafic réel :
`DATABASE_URL=... uv run python backend/scripts/seed_demo.py` ajoute un historique de flux et de requêtes.

Ajouter un composant shadcn : `pnpm dlx shadcn@latest add <composant>`.

## Image

```bash
docker build -t nemotron-frontend frontend
docker run -p 3000:8080 -e BACKEND_URL=http://backend:8000 nemotron-frontend
```

nginx sert l'application (repli sur `index.html` pour les routes) et `/healthz`. L'image tourne en lecture seule,
utilisateur 101.
