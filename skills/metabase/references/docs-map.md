# Metabase Docs Map

**Durable contract (won't rot):** the API index is generated per release and
lists every endpoint. Version-pin any URL below by replacing `latest` with the
instance's tag (e.g. `/docs/v0.57/api/card`); get the tag from
`GET /api/session/properties` → `version.tag`.

The URLs below are a convenience cache, validated by CI. **The Metabase API is
versioned with the app and changes between releases** — when
[api-reference.md](api-reference.md) is missing something or an endpoint
behaves unexpectedly, fetch the live page rather than guessing.

## API

- API index (all endpoints, generated per version) => https://www.metabase.com/docs/latest/api-documentation
- card endpoints => https://www.metabase.com/docs/latest/api/card
- dataset / query endpoints => https://www.metabase.com/docs/latest/api/dataset
- dashboard endpoints => https://www.metabase.com/docs/latest/api/dashboard
- search endpoint => https://www.metabase.com/docs/latest/api/search

## Auth and usage

- API keys & auth => https://www.metabase.com/docs/latest/people-and-groups/api-keys
- working with the API (guide) => https://www.metabase.com/learn/metabase-basics/administration/administration-and-operation/metabase-api

## Query syntax

- SQL parameters, `{{tag}}` and `[[optional]]` blocks => https://www.metabase.com/docs/latest/questions/native-editor/sql-parameters
