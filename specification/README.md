# Pinned API specification

These files are the input of `scripts/generate_sre_extension.py`. They are
verbatim copies from
[Azure/azure-rest-api-specs](https://github.com/Azure/azure-rest-api-specs)
at commit `2e17a47a7977184391c9ea8fd0f1e8f51d2cb563`, keeping the upstream
directory layout so relative `$ref`s resolve:

- `app/resource-manager/Microsoft.App/SreAgent/readme.md`
- `app/resource-manager/Microsoft.App/SreAgent/stable/2026-01-01/sreagent.json`
  and its `examples/`
- `common-types/resource-management/v6/types.json` and `managedidentity.json`
  (the only external references of `sreagent.json`)

To move to a newer API version, copy the new files from upstream, update the
commit above and the tag/api-version constants in the generator, then
regenerate (see [CONTRIBUTING.md](../CONTRIBUTING.md#regenerating-the-generated-code)).
