# Metabase docs map

The API has no separate version scheme. Available endpoints depend on the
installed Metabase release. For the deployed instance's documentation, open
`/api/docs` on that instance.

Public documentation archives use release-series paths, such as
`/docs/v0.57/api` and `/docs/v0.57/api.json`. The instance's `version.tag` can
include a patch number, so do not substitute the full tag for `latest`.
Public archives do not establish exact patch behavior.

CI checks that the marked URLs resolve. When [api-reference.md](api-reference.md)
lacks an endpoint or its behavior differs, consult the matching instance or
release documentation.

## API

- Interactive API reference, rendered with JavaScript => https://www.metabase.com/docs/latest/api
- OpenAPI schema for endpoint lookup => https://www.metabase.com/docs/latest/api.json

In the schema's `paths` object, find endpoints under `/api/card`,
`/api/dataset`, `/api/dashboard`, or `/api/search`. Match the HTTP method and
path, including any trailing slash in the applicable release.

## Auth and usage

- API keys & auth => https://www.metabase.com/docs/latest/people-and-groups/api-keys
- working with the API (guide) => https://www.metabase.com/learn/metabase-basics/administration/administration-and-operation/metabase-api

## Query syntax

- SQL parameters, `{{tag}}` and `[[optional]]` blocks => https://www.metabase.com/docs/latest/questions/native-editor/sql-parameters
