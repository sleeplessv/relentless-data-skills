# snowman wrapper: is CSV the right agent-facing result format?

Research date: 2026-09-03. Question: the `snowman` skill (`skills/snowman/`) returns query results to the agent as CSV (header row, empty cell for NULL, nested VARIANT/OBJECT/ARRAY as compact JSON, `# ...` footer lines, `--json` opt-in), and spills overflowing results in full to `.snowman/results/*.csv`. Is CSV the best choice for an LLM-driven workflow, or should the wrapper switch to (or offer) TSV, JSON, Markdown, or TOON? This note builds on `docs/research/snowman-wrapper-token-efficiency.md` (2026-09-03), which already established the byte and token gap between `snow --format JSON` and CSV, the Claude Code output limits, and Anthropic's tool-response guidance. It does not repeat those measurements; it adds format-vs-format comparisons on a controlled sample, parse-robustness analysis, and the published accuracy evidence. Installed Snowflake CLI at measurement time: 3.26.0 (the earlier note measured 3.25.0). Token counts below use `tiktoken` (`o200k_base`, `cl100k_base`) because `ANTHROPIC_API_KEY` was not set in this session; they are a proxy for Claude's tokenizer (see Appendix).

## Summary

1. **Keep CSV as the default head.** On a 50 x 8 mixed-type sample, CSV is the cheapest or within 12% of the cheapest of nine renderings, and it is the only one that is simultaneously (a) parseable by `csv`, pandas, and DuckDB with zero configuration, (b) truncation-safe (every prefix of the output is valid, so a cut at N rows or N characters still reads), and (c) readable as a saved file. No first-party (Anthropic, OpenAI, Snowflake) source prescribes a result format; Anthropic's own guidance is "there is no one-size-fits-all solution" and to keep responses high-signal (https://www.anthropic.com/engineering/writing-tools-for-agents).
2. **The one measurable weakness of CSV is quote-doubling inside nested-JSON cells.** On the sample, the `""` escaping of the VARIANT column costs 622 of 3,772 tokens (16%); TSV, which needs no quoting for `"` or `,`, comes in at 0.82x CSV. On the same rows with the VARIANT column removed, CSV and TSV are within 2% (1,638 vs 1,612 tokens), matching the earlier note's "within 1%" finding on real SHOW/DESCRIBE output. So the switch to TSV pays only for VARIANT-heavy results, where `--json` already exists.
3. **NULL vs empty string is genuinely ambiguous in CSV, and every consumer agrees on the wrong side of it.** Python's `csv` writes `None` as `""` and documents the transformation as "not reversible" (https://docs.python.org/3/library/csv.html); pandas reads the empty field as NaN by default (https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html); DuckDB's `nullstr` defaults to empty, so empty is NULL (https://duckdb.org/docs/current/data/csv/overview.html). A genuine empty-string cell is therefore indistinguishable from NULL in the head and in the saved file. The wrapper's `# empty cells are NULL` footer papers over this. Recommendation 2 below gives a cheap fix.
4. **Published accuracy evidence does not favour a switch.** The only controlled paper comparing CSV, TSV, JSON, Markdown, and HTML on flat tables (Singha et al. 2023, GPT-3 text-davinci-003) has comma-separated at 75.78% overall fact-finding pass@1 vs JSON 77.93%, TSV 75.80%, Markdown 67.32% (https://arxiv.org/abs/2310.10358). TOON's own benchmark, on four current models including Claude Haiku, has CSV at 62.2% vs TOON 63.1% on the flat-only track, inside the +/-4.5 confidence interval (https://toonformat.dev/guide/benchmarks). The one consistent signal across both is that Markdown tables are worse, and that all tabular formats (CSV, TSV, TOON) struggle relative to JSON on aggregation and filtering questions asked directly over the text. That last point argues for the existing snowman rule "narrow with SQL, not by reading rows", not for a format change.
5. **The `--format CSV` produced by `snow` itself is not what snowman emits, and it is worse.** Measured on 3.26.0: `snow sql --format CSV` writes booleans as Python `True`, and VARIANT as pretty-printed multi-line JSON inside a quoted cell (`"{\n  ""k"": 1\n}"`), which is valid CSV but breaks line-oriented reading. snowman's own rendering (`render_cell`: `true`/`false`, compact JSON) is the right call; keep parsing JSON_EXT and rendering in the wrapper.
6. **Concrete improvements, in order:** (a) a `# NULL` vs `""` distinction, cheapest as a per-column note or a `\N`-style marker (+1% tokens); (b) a one-line type header (or a `# types:` footer) so the agent knows `AMOUNT` is a scaled NUMBER and `ORDER_TS` is TIMESTAMP_NTZ, which no text format carries on its own; (c) leave TSV as an option only if VARIANT-heavy exploration turns out to be common, since `--json` already covers it.

## 1. What each first-party API says about tool-result format

Anthropic Messages API. A `tool_result` `content` is "a string ... a list of nested content blocks ... or a list of document blocks"; the block types are `text`, `image`, `document`, `search_result` (https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls). There is no structured/JSON result type; everything the model reads is text. The tool-definition page adds "Design tool responses to return only high-signal information ... include only the fields Claude needs to reason about its next step. Bloated responses waste context" (https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools).

Anthropic engineering guidance. "Tool response structure, for example XML, JSON, or Markdown, can have an impact on evaluation performance: there is no one-size-fits-all solution", and the recommended lever is a `response_format` enum (`concise` / `detailed`), pagination, filtering, and truncation "with sensible default parameter values" (https://www.anthropic.com/engineering/writing-tools-for-agents). The context-engineering post's relevant claim is context rot: "as the number of tokens in the context window increases, the model's ability to accurately recall information from that context decreases", so tokens spent on format overhead are not free even when they fit (https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents). Chroma's Context Rot study across 18 models (including Claude 4 and GPT-4.1) confirms the direction: "model performance varies significantly as input length changes, even on simple tasks", and "even a single distractor reduces performance" (https://www.trychroma.com/research/context-rot).

OpenAI. "The result you pass in the `function_call_output` message should typically be a string, where the format is up to you (JSON, error codes, plain text, etc.)" (https://developers.openai.com/api/docs/guides/function-calling). No format preference is stated.

Claude Code harness. Bash results are delivered "Inline up to roughly 30,000 characters; past that, the path of a file saved to the session directory ... plus a short preview from the start"; failures get a 10,000-character head-and-tail excerpt (https://code.claude.com/docs/en/tools-reference). Observed in this session: a 29.3 KB stdout was replaced by "Output too large (29.3KB). Full output saved to ... Preview (first 2KB)". That preview mechanism is why prefix-validity matters (section 4).

Snowflake CLI. `--format [TABLE|JSON|JSON_EXT|CSV]`, JSON "Returns JSON as quoted strings", JSON_EXT "Returns JSON as JSON objects" (https://docs.snowflake.com/en/developer-guide/snowflake-cli/command-reference/sql-commands/sql). The docs say nothing about NULL rendering; the source does: CSV writes `None` as `""` via `csv.DictWriter` with default `QUOTE_MINIMAL`, and non-date, non-Decimal values via `str(value)` (`_app/printing.py`, https://github.com/snowflakedb/snowflake-cli/blob/v3.25.0/src/snowflake/cli/_app/printing.py). Measured on 3.26.0 against a real account with `select 1 as a, null as b, '' as c, 'x,y' as d, object_construct('k',1,'n',null) as o, 1.50::number(10,2) as n, true as t, current_date() as dt`:

| format | NULL (B) | empty string (C) | comma string (D) | VARIANT (O) | NUMBER(10,2) (N) | BOOLEAN (T) |
|---|---|---|---|---|---|---|
| CSV | empty | empty | `"x,y"` | `"{\n  ""k"": 1\n}"` (3 physical lines) | `1.50` | `True` |
| JSON | `null` | `""` | `"x,y"` | `"{\n  \"k\": 1\n}"` (escaped string) | `"1.50"` (string) | `true` |
| JSON_EXT | `null` | `""` | `"x,y"` | real object, indent 4 | `"1.50"` (string) | `true` |
| TABLE | `None` | blank | `x,y` | pretty JSON across 3 rows | `1.50` | `True` |

So the raw CLI's CSV is unusable as an agent-facing format without the wrapper's post-processing (multi-line VARIANT cells, `True`), and even JSON_EXT loses numeric type for any NUMBER with a scale. The wrapper's decision to parse JSON_EXT and render its own CSV is correct and should stay.

## 2. Token cost, measured on a controlled sample

Sample: 50 rows x 8 columns generated in `measure_formats.py` (scratchpad, not committed): `ORDER_ID` int, `CUSTOMER_EMAIL` string, `ORDER_TS` ISO timestamp, `STATUS` string with 20% NULL, `AMOUNT` two-decimal string (as JSON_EXT delivers scaled NUMBER), `IS_GIFT` boolean, `NOTE` free text with embedded commas, double quotes, one newline, one accented string, some NULL and one genuinely empty string, `PAYLOAD` a nested VARIANT (`{"items":[...],"ship":{...}}`) with 1 in 7 NULL. Every rendering carries the same values; TOON is rendered per the spec's tabular form (`rows[50]{f1,f2,...}:`, quoting rules from https://github.com/toon-format/spec/blob/main/SPEC.md §7), with the non-uniform `PAYLOAD` column emitted as a quoted compact-JSON string, because TOON's tabular form requires uniform rows and the sample is not uniform.

| format | bytes | o200k_base tokens | cl100k_base tokens | vs CSV (o200k) |
|---|---|---|---|---|
| CSV (snowman today) | 9,703 | 3,772 | 3,746 | 1.00x |
| CSV with `\N` for NULL | 9,757 | 3,820 | 3,794 | 1.01x |
| TSV (backslash-escaped, no quoting) | 8,651 | 3,079 | 3,059 | 0.82x |
| JSON array of objects, compact | 13,471 | 4,432 | 4,396 | 1.17x |
| JSON array of objects, indent=4 (`snow --format JSON`) | 28,526 | 7,163 | 7,169 | 1.90x |
| NDJSON | 13,469 | 4,480 | 4,444 | 1.19x |
| JSON columnar `{columns, rows}` | 9,376 | 3,301 | 3,257 | 0.88x |
| Markdown table | 9,619 | 3,517 | 3,492 | 0.93x |
| TOON tabular | 10,046 | 3,369 | 3,333 | 0.89x |

Same rows, `PAYLOAD` column dropped (7 scalar columns), to isolate the effect of the nested column:

| format (7 scalar cols, no VARIANT) | bytes | o200k_base tokens |
|---|---|---|
| CSV | 4,403 | 1,638 |
| TSV | 4,347 | 1,612 |
| JSON compact objects | 8,642 | 2,833 |
| JSON columnar | 5,037 | 1,832 |
| Markdown | 5,209 | 2,004 |

Observations:

- The whole CSV-vs-TSV gap is quote-doubling. Collapsing every `""` in the 8-column CSV back to `"` (an invalid file, but a fair token count of the escaping overhead) gives 3,150 tokens, i.e. 622 tokens (16%) spent on RFC 4180 escaping of the JSON cells. With no nested column CSV and TSV differ by 26 tokens (1.6%), consistent with the earlier note's real-account measurements.
- Markdown is cheaper than CSV here (0.93x) only because the sample's JSON cells contain no `|` and Markdown needs no `""` doubling; with the scalar-only rows Markdown is 22% more expensive than CSV, matching the earlier note's 10 to 40% on real data. Markdown also loses newlines (`<br>`) and cannot represent a `|` without a backslash convention no CSV reader knows.
- TOON and JSON-columnar land at 0.88 to 0.89x for the same reason as TSV: neither doubles quotes. TOON's own flat-track benchmark reports the opposite ordering (CSV 47,153 vs TOON 49,978 tokens on employee records, TOON +6%; https://toonformat.dev/guide/benchmarks) because their flat data has no embedded quotes. Both results are correct for their data; on a VARIANT-free result CSV is the floor.
- Compact array-of-objects JSON is 1.17x CSV here and 1.73x on the scalar-only rows; pretty JSON (what `snow --format JSON` emits) is 1.90x. This is the repeated-keys cost the earlier note quantified on real output (1.8x to 3x).
- `cl100k_base` and `o200k_base` agree to within 1.5% on every row, which is weak evidence that the ordering is not a tokenizer artefact. Claude's tokenizer is different again, and Anthropic notes that Claude 4.7 and later models "produce approximately 30 percent more tokens" than earlier models on the same text (https://platform.claude.com/docs/en/build-with-claude/token-counting); the absolute numbers will shift, the ratios are what to read.

## 3. Parse robustness for the agent

CSV. RFC 4180 (informational, not a standard) requires fields containing commas, quotes, or line breaks to be quoted and internal quotes doubled, and defines no null (https://www.rfc-editor.org/rfc/rfc4180). Python's writer writes `None` as the empty string and the docs call this "not a reversible transformation" (https://docs.python.org/3/library/csv.html); the reader hands both `""` and an empty field back as `''` (verified in `measure_formats.py`: rows whose `NOTE` was `None` and `""` both read back as `''`). Python 3.12 added `QUOTE_NOTNULL` and `QUOTE_STRINGS`, which write `None` as an unquoted empty field and quote real strings, and teach the reader to "interpret an empty (unquoted) field as `None`" (same page). That is a standards-compatible way to make NULL distinguishable, but only for consumers that opt into the same quoting mode; pandas and DuckDB do not by default. Embedded newlines are legal in CSV but make the head non-line-oriented: an agent counting rows by counting lines, or `grep`ping the head, sees the wrong thing. The `# ` footer convention is safe because `write_csv_row` force-quotes a first cell starting with `#`.

TSV (jq `@tsv` convention). "Input characters line-feed, carriage-return, tab and backslash will be output as escape sequences \n, \r, \t, \\" (https://jqlang.org/manual/). No quoting at all, so one physical line is always one row, and `,` and `"` cost nothing. The price is that a `\n` in a cell is now a literal two-character sequence that `csv.reader(delimiter="\t")`, pandas `sep="\t"`, and DuckDB will *not* unescape (they follow the CSV quoting model, not the backslash model), so a TSV head needs its own reader to round-trip newlines. DuckDB and pandas both handle a tab delimiter with one argument (`delim`/`sep`, https://duckdb.org/docs/current/data/csv/overview.html; https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html), and DuckDB auto-detects it.

JSON (array of objects, columnar, NDJSON). Unambiguous null, string vs number distinction, nested values native, and `jq` reads it directly ("The input to jq is parsed as a sequence of whitespace-separated JSON values", https://jqlang.org/manual/). DuckDB's `read_json` accepts array, newline-delimited, and `auto` layouts and maps arrays to LIST and objects to STRUCT (https://duckdb.org/docs/current/data/json/loading_json.html). Two caveats specific to Snowflake: the CLI emits scaled NUMBER as a JSON string (`"1.50"`, measured above and documented in `references/guardrails.md`), so "type fidelity" is only partial; and array-of-objects is not prefix-valid (section 4). `--json` already gives snowman users this path.

Markdown table. No escaping standard for `|` or newlines (GFM's `\|` convention is renderer-specific), no null, no consumer library. It is the format Singha et al. found weakest on every task (Table 1 and 2, https://arxiv.org/abs/2310.10358). Not a candidate.

TOON. Explicit `null` literal, explicit row count in the header (`[50]`), typed unquoted numbers by grammar (`/^-?[0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?$/i`, spec §4), tab or pipe delimiters, and quoting only for strings containing the delimiter, `:`, `"`, `\`, or matching `true|false|null` (spec §7, https://github.com/toon-format/spec/blob/main/SPEC.md). Its declared length is the one feature no other format has: the spec's stated use case includes "explicit lengths and fixed row widths help detect truncation or malformed data". Against that: nothing in the pandas/DuckDB/jq ecosystem reads it; the tabular form only applies when every row has the same fields, which a VARIANT column violates; and the project's own README says not to use it when "data is purely tabular" because "CSV is smaller" (https://github.com/toon-format/toon). snowman already appends `# showing 50 of 1203 rows`, which gives the agent the same truncation signal as TOON's `[N]`.

Type fidelity across all text formats. None of CSV, TSV, Markdown, or TOON carries column types; JSON carries string vs number vs bool vs null but, from this CLI, only for unscaled integers. Snowflake's `DESCRIBE` or a `->> SELECT "name","type" FROM $1` projection is the only source of truth, and the wrapper could surface it cheaply (recommendation 3).

## 4. Streamability and truncation

CSV, TSV, NDJSON, and TOON are line-oriented: every prefix that ends on a line boundary is a valid, self-describing document (header plus N rows), so a cap at `--max-rows`, the harness's 2 KB preview, or a `head -20` on the saved file all read cleanly. This is what the Claude Code spill behaviour rewards ("a short preview from the start", https://code.claude.com/docs/en/tools-reference). Array-of-objects JSON and columnar JSON are not prefix-valid: a 2 KB preview of a 30 KB array is an unclosed literal, and `jq` or `json.loads` rejects it. Pretty JSON is worst, since a single row spans many lines. NDJSON is prefix-valid but repeats keys per row (1.19x CSV). Markdown is prefix-valid but has no reader.

CSV's one streaming defect is the embedded newline: a quoted cell containing `\n` breaks the "one line, one row" property, so a preview cut at a line boundary can end mid-record. The wrapper's `--max-cell` cap does not remove newlines. This is the strongest argument for the jq-style TSV escaping, or for rewriting `\n` inside CSV cells as the literal `\n` (a lossy but line-safe choice that the footer can announce).

## 5. Interoperability: what the agent can pipe the head or the file into

| consumer | CSV | TSV | JSON array | NDJSON | Markdown | TOON |
|---|---|---|---|---|---|---|
| `python -c "import csv"` | yes | `delimiter="\t"`, no unescape of `\n` | `json.loads` | line-wise `json.loads` | no | no |
| pandas | `read_csv` | `read_csv(sep="\t")` | `read_json` | `read_json(lines=True)` | no | no |
| DuckDB | `read_csv` auto-detect | auto-detect | `read_json` | `read_json` | no | no |
| jq | via `-R` + `split(",")` (no quoting support) | `-R` + `split("\t")` | native | native | no | no |
| a human opening `.snowman/results/*.csv` | spreadsheet, editor | spreadsheet, editor | editor, needs formatting | editor | renders in a Markdown viewer | editor |

Sources: pandas `sep` and `na_values` (https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html); DuckDB CSV `delim`, `nullstr`, `auto_detect` (https://duckdb.org/docs/current/data/csv/overview.html); DuckDB JSON layouts (https://duckdb.org/docs/current/data/json/loading_json.html); jq `-R`, `@csv`, `@tsv` (https://jqlang.org/manual/). CSV and TSV have the widest reach; JSON has the best fidelity for nested values; TOON has none of the ecosystem. Note that jq cannot parse quoted CSV, so an agent that wants jq should ask for `--json`, which is what SKILL.md already says.

## 6. How well models read each format

Singha et al., "Tabular Representation, Noisy Operators, and Impacts on Table Structure Understanding Tasks in LLMs" (arXiv 2310.10358, GPT-3 `text-davinci-003`, temperature 0, flat tables with header). Fact-finding pass@1 (Table 1): DFLoader 79.79, JSON 77.93, TSV 75.80, CSV 75.78, DataMatrix 72.64, HTML-no-space 72.00, HTML 71.40, Markdown 67.32. Transformation F1 (Table 2): DFLoader 98.55, JSON 94.89, CSV 89.55, HTML-no-space 83.55, TSV 78.55, HTML 73.11, DataMatrix 61.11, Markdown 36.11. The authors' explanation for JSON's edge on navigation is that it "repeats headers locally", and for Markdown they conclude "such a format should not be used for prompts for tabular data" (https://arxiv.org/abs/2310.10358). CSV and TSV are statistically indistinguishable on fact-finding; the 2.15-point gap to JSON on fact-finding is real but small and paid for with 1.7x to 1.9x the tokens (section 2).

Sui et al., "Table Meets LLM" (WSDM 2024, GPT-3.5 with GPT-4 subsets) found HTML best among NL+Sep, Markdown, JSON, XML, HTML on their structural-understanding benchmark, "outperforms NL+Sep with a 6.76% improvement" (https://arxiv.org/abs/2305.13062). Singha et al. explicitly contradict this on flat tables ("we find that HTML does not seem to provide the best performance"), and note HTML's verbosity means "up to half as many rows being included". TabVerse (arXiv 2606.09578, June 2026) compares HTML, Markdown, and LaTeX only, finds HTML "often the safest text format for text-input pipelines", and does not test CSV or JSON or report token cost (https://arxiv.org/html/2606.09578). None of these argues for HTML in a tool result: the token cost is prohibitive and the row-count ceiling it imposes is exactly the opposite of what a result head needs.

TOON benchmarks (https://toonformat.dev/guide/benchmarks; methodology in https://github.com/toon-format/toon). 244 questions x 6 formats x 4 models (Claude Haiku, Gemini 3.6 Flash, GPT-5.4-nano, Grok-4.5), reasoning disabled, `o200k_base` for token counts. Flat-only track (109 questions where CSV applies): TOON 63.1 +/-4.5, CSV 62.2 +/-4.5, JSON pretty 60.3 +/-4.6. By question type across all datasets: field retrieval CSV 100%, TOON 97.8%, JSON 99.2%; aggregation CSV 32.8%, TOON 48.4%, JSON 48.4%; filtering CSV 33.3%, TOON 38.0%, JSON 41.1%. The page's own caveat: "CSV answers only the 109 flat-dataset questions, so its per-model cells cover a smaller, easier population than the other formats." A community re-run on 34 models and 3,026 tests (toon-format/toon discussion #285) reports YAML 83.0%, JSON pretty 81.0%, JSON compact 79.6%, TOON 77.4%, CSV 69.7%, with the author attributing the tabular formats' weakness on filtering (JSON 78.7% vs TOON 66.9%, CSV 64.7%) to "a tabular format problem, not a TOON problem", and noting "top-tier models showed zero accuracy gaps between TOON and JSON" (https://github.com/toon-format/toon/discussions/285). Issue #72 on the same repo makes the point that TOON's token pitch does not hold against CSV on tabular data (https://github.com/toon-format/toon/issues/72); the README now concedes it.

What this means for snowman. The accuracy gap between CSV and JSON shows up on aggregation and filtering questions answered by reading rows. snowman's guardrails already say to do that work in SQL (`GROUP BY`, `WHERE`, `COUNT`), and its head is capped at 50 rows precisely so the agent does not aggregate over text. For field retrieval, which is what an agent does with a 50-row head ("what is the status of order 100003?"), CSV is at or near 100% in every study. The evidence therefore supports keeping CSV for the head and steering aggregation into SQL, which is the current design.

## 7. Human readability of the saved file

`.snowman/results/*.csv` opens in a spreadsheet, `column -s, -t`, DuckDB, pandas, and any editor; the header row makes it self-describing; and the file is byte-identical to what a `csv.DictWriter` would produce, so no reader needs a flag. Pretty JSON reads well in an editor but is not spreadsheet-openable and is 2.9x the bytes (28,526 vs 9,703 on the sample). NDJSON needs `jq` to be readable at all. TSV is as readable as CSV in a spreadsheet, slightly less in a terminal because tabs collapse visually. The NULL/empty ambiguity applies to the file as much as to the head, and the file has no footer to warn about it, so a human reading the saved file has no way to know whether a blank was NULL.

## Recommendations for snowman

1. **Keep CSV as the default agent-facing head and as the spill format.** Cheapest or near-cheapest on scalar results (section 2), prefix-valid (section 4), widest tool reach (section 5), best-read tabular format in the one study that tested it against TSV and Markdown (section 6). Keep the wrapper's own rendering rather than `snow --format CSV` (section 1: `True`, multi-line VARIANT).
2. **Make NULL distinguishable from empty string.** Cheapest option that stays reader-compatible: keep empty-for-NULL and quote genuine empty strings as `""`, then replace the footer with `# NULL is an empty cell; an empty string is ""`. Python's `QUOTE_NOTNULL`/`QUOTE_STRINGS` (3.12+) are the documented mechanism for readers that opt in (https://docs.python.org/3/library/csv.html); pandas and DuckDB will still read `""` as NULL/NaN by default (`allow_quoted_nulls` is on by default in DuckDB, https://duckdb.org/docs/current/data/csv/overview.html), so the file consumer needs `keep_default_na=False` or `allow_quoted_nulls=false` to see the difference. The alternative marker `\N` costs +1% tokens (measured) and is what DuckDB's `nullstr` and pandas `na_values` can be pointed at, but it is not what any reader assumes by default. Either way, only emit the footer when the result actually contains both kinds of cell; today it fires on any NULL.
3. **Add a `# types:` footer (or a second header line) when a result has NUMBER-with-scale, TIMESTAMP, or VARIANT columns.** JSON_EXT itself carries no column metadata (it is a bare array of row objects), so the wrapper appends `DESCRIBE RESULT LAST_QUERY_ID()` as a second statement; measured on 3.26.0, snow then prints `[[rows], [describe rows]]` for SELECT, SHOW, and `->>` pipes, `[[], [describe rows]]` for an empty result, and `[]` with exit 5 when the query fails (implemented 2026-09-03). No text format carries types (section 3), snow renders scaled NUMBER as a string even in JSON (section 1), and the accuracy studies agree data-type lookup is the one task every format does well on *when the type is visible* (Singha et al. DataTypeLookup 84 to 96% across formats). One footer line is cheaper than an extra DESCRIBE round trip.
4. **Do not switch to TSV globally.** Its 18% saving on the sample is entirely the VARIANT column's quote-doubling; on scalar results it is 1.6%. A VARIANT-heavy result is the case `--json` exists for. If newline-in-cell turns out to break previews in practice, the smaller change is to escape `\n` as the two characters `\n` inside CSV cells (announce it in the footer), which keeps CSV readers working and restores one-line-per-row.
5. **Do not adopt TOON.** Its only unique benefit (declared row count) is already provided by the `# showing N of M rows` footer; the ecosystem cannot read it; its own benchmark shows no meaningful accuracy gain over CSV on flat data on current models; and its tabular form cannot represent a VARIANT column without falling back to a quoted JSON string, which is what CSV already does.
6. **Do not offer a Markdown or HTML option.** Markdown is the weakest format in every study that measured it and costs 10 to 40% more than CSV on real output; HTML is best only in the one study that did not test CSV, and its verbosity halves the rows that fit.
7. **Keep `--json` as the per-call option, and say in SKILL.md when to use it:** nested VARIANT results the agent will `json.loads` or `jq`, or a result where the NULL/empty distinction matters and recommendation 2 has not landed. That is the `response_format`-style switch Anthropic recommends (https://www.anthropic.com/engineering/writing-tools-for-agents), and it already exists. A `--tsv` flag is not worth its documentation cost.

## Appendix: measurement method

Script: `measure_formats.py` and `measure_variant.py` in the session scratchpad (not committed), Python 3 with `tiktoken` 0.14.0 in a venv. `ANTHROPIC_API_KEY` was not set (`env | grep -c ANTHROPIC_API_KEY` returned 0), so the Anthropic `count_tokens` endpoint (https://platform.claude.com/docs/en/api/messages-count-tokens) was not used; both OpenAI encodings were run and agree within 1.5%. Anthropic publishes no local tokenizer, and states that the tokenizer introduced with Claude Opus 4.7 (shared by Fable 5.x and Mythos 5.x) counts "roughly 30 percent higher than on models before" it (https://platform.claude.com/docs/en/build-with-claude/token-counting), so absolute counts for Claude will be higher; the ratios between formats are the finding. The CSV renderer in the script is the same `csv.writer(lineterminator="\n")` plus `render_cell` logic as `skills/snowman/scripts/snowman.py`, so the "CSV (snowman today)" row is what the wrapper emits for these rows. The `snow` measurements in section 1 were run with `snow sql ... --format {CSV,JSON,JSON_EXT,TABLE}` against the `xplor-uswe-aws-corp-dev` connection on Snowflake CLI 3.26.0.

Not verified: how Claude's tokenizer treats `""` sequences relative to `o200k_base` (the 16% quote-doubling figure could move either way); whether the Claude Code 2 KB preview cuts on a line boundary (observed once, not documented); TOON's benchmark harness beyond what its page states.

## Sources

- https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools
- https://platform.claude.com/docs/en/build-with-claude/token-counting
- https://platform.claude.com/docs/en/api/messages-count-tokens
- https://www.anthropic.com/engineering/writing-tools-for-agents
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- https://code.claude.com/docs/en/tools-reference
- https://developers.openai.com/api/docs/guides/function-calling
- https://docs.snowflake.com/en/developer-guide/snowflake-cli/command-reference/sql-commands/sql
- https://docs.snowflake.com/en/developer-guide/snowflake-cli/sql/execute-sql
- https://github.com/snowflakedb/snowflake-cli/blob/v3.25.0/src/snowflake/cli/_app/printing.py
- https://github.com/toon-format/toon
- https://github.com/toon-format/spec/blob/main/SPEC.md
- https://toonformat.dev/guide/benchmarks
- https://github.com/toon-format/toon/discussions/285
- https://github.com/toon-format/toon/issues/72
- https://arxiv.org/abs/2310.10358 (Singha, Cambronero, Gulwani, Le, Parnin, "Tabular Representation, Noisy Operators, and Impacts on Table Structure Understanding Tasks in LLMs", 2023)
- https://arxiv.org/abs/2305.13062 (Sui, Zhou, Zhou, Han, Zhang, "Table Meets LLM", WSDM 2024)
- https://arxiv.org/html/2606.09578 (Ahsan, Ahmad, Hee, Lee, Nakov, "TabVerse", 2026)
- https://www.trychroma.com/research/context-rot
- https://www.rfc-editor.org/rfc/rfc4180
- https://docs.python.org/3/library/csv.html
- https://duckdb.org/docs/current/data/csv/overview.html
- https://duckdb.org/docs/current/data/json/loading_json.html
- https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html
- https://jqlang.org/manual/
- `docs/research/snowman-wrapper-token-efficiency.md` (this repo, 2026-09-03)
