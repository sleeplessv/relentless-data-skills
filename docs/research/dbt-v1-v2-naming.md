# dbt engine naming: dbt v1, dbt v2, and the end of "dbt Fusion"

Research date: 2026-10-09. Question: has dbt Fusion been rebranded to just "dbt", so that there is dbt v1 and dbt v2?
This note backs the naming used in `skills/dbt-runner/` (PRs #85 and #86).

## Summary

**Mostly yes, with one correction.** dbt Labs renamed the dbt Fusion engine to **"dbt"** when v2 went GA. dbt Summit 2026 announced the change, and the GA blog is dated 2026-09-16. The docs do split versions into **dbt v1** (the Python 1.x line) and **dbt v2** (the Rust 2.x line). The correction: v2 ships as **two distributions**. One is **dbt**, formerly the dbt Fusion engine, under a proprietary licence that is free to use. The other is **dbt OSS**, formerly "dbt Core v2", under Apache 2.0. So "dbt v2" is the generation, not only the ex-Fusion binary. "dbt Core" now names only the v1 Python line, for example "dbt Core 1.12" and "dbt Core 1.13".

## 1. Official names and the announcement

- The engine formerly called Fusion is now **"dbt"**. dbt Labs writes "dbt v2" or "the full dbt distribution" when it needs to be clear, and "dbt (formerly known as the dbt Fusion engine)" on the licensing page.
  - "the dbt Fusion engine has graduated into General Availability under its new name: dbt." Source: https://docs.getdbt.com/blog/dbt-v2-is-ga (Sep 16, 2026)
  - "The **dbt Fusion engine is now just called dbt**, and **dbt Core v2 is now called dbt OSS**." Source: https://docs.getdbt.com/blog/comparing-dbt-and-dbt-oss (Sep 16, 2026)
  - FAQ: "What happened to dbt Fusion? It is now just called dbt." (same page)
- **dbt Core** splits two ways:
  - The v1 Python line stays "dbt Core 1.x". The versioning docs call it "dbt v1": "dbt v2 is the current generation of dbt and uses the 2.x release series. dbt v1 is the Python-based generation and stays on the 1.x series." Source: https://docs.getdbt.com/docs/dbt-versions (Sep 16, 2026)
  - "dbt Core v2" is renamed "dbt OSS". "The dbt Core name no longer applies to any dbt v2 distribution." Source: https://www.getdbt.com/licenses-faq. The change log there reads: "September 15, 2026: Updated dbt Fusion engine and dbt Core v2 references to dbt and dbt OSS respectively".
  - The Summit post says: "dbt Core isn't going anywhere either… still Apache 2.0, still open source, simply renamed as the previous version, dbt v1." Source: https://www.getdbt.com/blog/dbt-summit-2026-product-announcements (2026-09-16)
- **Capitalization dbt Labs uses:** "dbt", "dbt v2", "dbt v1", "dbt OSS" (product name), `dbt-oss` (package), "dbt Core 1.12" and "dbt Core v1" for the v1 line, and "dbt v2.0" in titles. "dbt 2.0.0" is the release title. dbt Labs does not write "dbt Core v1" as a new brand. It is simply what the v1 line has always been called.
- **Announcement timing:** v2.0.0 was released on GitHub 2026-09-14 ("dbt 2.0.0 - Benjamin Franklin"). The licensing page changed on 2026-09-15. The blog posts and Summit keynote followed on 2026-09-16.

## 2. Versions and `dbt --version`

- v2 is GA. The v2.0 release table reads "initial release Sept 14, 2026, Active support — Sept 13, 2027". The latest patch is **2.0.8**: the releases page shows it on the "latest" channel as of 2026-10-09, and GitHub releases shows v2.0.5 as of Sep 18. Source: https://docs.getdbt.com/docs/dbt/dbt-releases
- On the dbt platform, v2 is GA. Adapter status is mixed. GA: BigQuery, Databricks, DuckDB, Redshift and Snowflake. Beta: ClickHouse and Spark. Coming soon: Athena, Fabric and Postgres. Source: the Summit post.
- v1 still means dbt Core 1.x. The latest v1 line is 1.12, released Jul 16, 2026 with active support until Jul 15, 2027. "dbt Core 1.13 will be the final minor version of the 1.x vintage" (comparing-dbt-and-dbt-oss).
- Sample `dbt --version` output:
  - v2, from https://docs.getdbt.com/reference/commands/version: `dbt 2.0.1`. JSON form: `{"version": "2.0.1"}` via `--format json`.
  - v2, from https://docs.getdbt.com/docs/dbt-versions: `dbt v2 2.0.0`. **This differs from the command reference above.** A search snippet says the terminal guide still shows `dbt-fusion 2.0.1`; that page was not fetched to check.
  - v1 (unchanged): `Core:\n  - installed: 1.x.y ...\nPlugins: ...`
  - The v2.0.0 release notes say: "Rename dbt v2 CLI branding from Fusion/dbt-core to dbt (proprietary) and dbt-oss (OSS), updating --version/--help output". Before this, Fusion printed `dbt-fusion 2.0.0-preview.N` or `-beta`.
  - The docs give no sample output for dbt OSS. They only say "Confirm the installed version begins with `2.`" (install-dbt-v2 page).
  - **Safe detection rule:** a version starting with `2.` means v2 (dbt or dbt OSS). A `Core:` block with `installed: 1.x` means v1. Do not match on the exact v2 string.

## 3. CLI, install and packages

- The binary is still **`dbt`** for v1, dbt v2 and dbt OSS alike.
- **The `dbtf` alias still exists.** The curl installer "adds a `$PATH` export and a `dbtf` alias to `~/.zshrc` or `~/.bashrc`": `alias dbtf=$HOME/.local/bin/dbt`. Source: https://docs.getdbt.com/docs/local/install-dbt (Oct 7, 2026)
- The curl install URLs are unchanged, including the `/fs/` path: `curl -fsSL https://public.cdn.getdbt.com/fs/install/install.sh | sh -s -- --update`. PowerShell: `irm https://public.cdn.getdbt.com/fs/install/install.ps1 | iex`. The binary goes to `~/.local/bin/dbt`.
- `dbt system update` still works for curl and PowerShell installs only, with channels `--version canary|dev|2.0.0`.
- New install routes:
  - pip: `python -m pip install dbt` for the full distribution, or `pip install dbt-oss`.
  - Homebrew: `brew tap dbt-labs/dbt && brew install dbt-labs/dbt/dbt`.
  - winget: `winget install --id dbtLabs.dbt --exact`.
- Adapters no longer need installing ("driver is downloaded on-demand"). `pip install dbt-snowflake` still works and bundles dbt plus the ADBC driver.
- "For now, `pip install dbt-core` will continue to work (and will install dbt OSS)". If nothing pins `dbt-core` below 2.0, it now pulls in v2.
- The GitHub repo is **dbt-labs/dbt**. Its `main` branch holds v2 Rust code under Apache 2.0, and "dbt v1 development has moved to the `1.latest` branch." The old dbt-labs/dbt-fusion repo is described as "ARCHIVE: code & issue tracking in dbt-core".
- The v1 flag `--use-v2-parser` (on dbt Core 1.12+) checks a project for v2 compatibility. Inside v1, internal "Fusion" names were renamed to "V2" (dbt-labs/dbt PR #16281, merged 2026-09-18; for example `V2ParserError`).
- The VS Code extension is now called "dbt" (`dbtLabsInc.dbt`) and is "powered by the new dbt v2 engine".

**Where "Fusion" still appears officially (leftovers only):**
- The `dbtf` alias.
- The `/fs/` install path.
- The licence URL `dbt-fusion-engine-license-agreement`.
- The github.com/dbt-labs/dbt-fusion links in docs.
- Old docs URLs under `/docs/fusion/...`. They now serve "dbt v2" pages; the canonical paths are under `/docs/dbt/...`.
- The internal error code `UnsupportedFusionFeature`.
- Pre-GA release notes.

Current docs prose does not use "Fusion" as a product name.

## 4. Names retired explicitly

- "dbt Fusion" and "dbt Fusion engine" are replaced by "dbt". ("It is now just called dbt.")
- "dbt Core v2" and "dbt Core 2.0" are replaced by "dbt OSS". ("swapping the dbt Core v2 name for dbt OSS"; "The dbt Core name no longer applies to any dbt v2 distribution.")
- "dbt Core" as shorthand for "the free or local version of dbt" is discouraged: "Historically, it's been common to use 'dbt Core' as a shorthand for... In the v2 era, only one of those remains a unique differentiator."
- No explicit rule against using "dbtf" was found. It is simply still there.

## 5. Open or ambiguous points

- The exact `dbt --version` string for v2 is inconsistent across the docs (`dbt 2.0.1` vs `dbt v2 2.0.0`). Output for dbt OSS is not documented. Check against a real install.
- The Summit wording "simply renamed as the previous version, dbt v1" is loose. The version docs use "dbt v1" for the generation. Other posts still say "dbt Core 1.12" and "dbt Core 1.13". Both are in use, and neither is listed as retired.
- GitHub release assets for v2.0.5 are still named `dbt-core-2.0.5-*` and `dbt_core-2.0.0rc8-*.whl`, so packaging naming is not fully migrated.
- Whether `dbtf` will be removed in future was not checked.

## Naming to use in skills

| Old term | New term |
|---|---|
| dbt Fusion, the dbt Fusion engine, Fusion | **dbt v2**. Write plain **dbt** only where the generation is obvious. On first use you may add "(formerly dbt Fusion)". |
| dbt-fusion (CLI quirks, `dbt-fusion 2.0.0-preview` versions) | dbt v2 (the CLI reports `2.x`) |
| dbt Core v2, dbt Core 2.0 | **dbt OSS**. The package is `dbt-oss`. |
| dbt Core (meaning the Python engine) | **dbt v1**, or dbt Core 1.x when naming a specific version (for example dbt Core 1.12) |
| "dbt Core" meaning "free" or "local" dbt | Don't use it this way. Both v2 distributions are free and local. |

**Keep as they are:**
- The binary `dbt`.
- The `dbtf` alias. The installer still creates it, so detecting it is still valid.
- `dbt system update`.
- The curl and PowerShell install URLs under `/fs/install/`.
- `dbt-<adapter>` packages, which still work.
- `dbt-core` as a pip package name for v1. Note that unpinned `pip install dbt-core` now installs dbt OSS v2.
- `--use-v2-parser` on v1.12 or later.
- Version detection by major version (1.x vs 2.x), not by the "Fusion" string.

## Sources

1. https://docs.getdbt.com/blog/dbt-v2-is-ga ("dbt v2.0 is GA", Joel Labes, Sep 16, 2026)
2. https://docs.getdbt.com/blog/comparing-dbt-and-dbt-oss ("What's the difference between dbt and dbt OSS?", Sep 16, 2026)
3. https://www.getdbt.com/licenses-faq (dbt Licensing FAQ, change log entry 2026-09-15)
4. https://www.getdbt.com/blog/dbt-summit-2026-product-announcements (2026-09-16)
5. https://docs.getdbt.com/docs/dbt-versions (Sep 16, 2026)
6. https://docs.getdbt.com/reference/commands/version (Sep 16, 2026)
7. https://docs.getdbt.com/docs/local/install-dbt (Oct 7, 2026)
8. https://docs.getdbt.com/docs/local/install-dbt-v2 ("Install dbt OSS", Sep 16, 2026)
9. https://docs.getdbt.com/docs/dbt/dbt-releases (Sep 22, 2026; latest v2.0.8)
10. https://docs.getdbt.com/docs/dbt/dbt-readiness (Oct 7, 2026)
11. https://github.com/dbt-labs/dbt/releases and https://github.com/dbt-labs/dbt/releases/tag/v2.0.0
12. https://github.com/dbt-labs/dbt (README) and https://github.com/dbt-labs/dbt/pull/16281
13. https://marketplace.visualstudio.com/items?itemName=dbtLabsInc.dbt
