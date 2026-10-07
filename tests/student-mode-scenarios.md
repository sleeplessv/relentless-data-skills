# Student-mode behavioral scenarios

Run each scenario in a fresh conversation. Invoke `/student-mode` first, then
give the agent only the prompt and supplied context. Assess the shape of the
code and the response against the observable outcomes below. These are
behavioral checks, not assertions about exact wording. They require no live
services.

## CSV summary in Python

Prompt:

> I have `sales.csv` with columns `region` and `amount`. Show me
> the total amount per region.

Supplied context: an empty directory.

Observe one Python file, read top to bottom, using `pandas` or `csv` from the
standard library. No functions, no classes, no try/except, no type hints, no
`if __name__ == "__main__"`. Comments say why, not what. The prose is one or
two sentences, with no mention of what production code would add.

## Sticky across requests

Follow the CSV scenario with:

> Now also show the average amount per region.

Observe that the code stays in the same single-file shape. The agent does not
refactor into functions or add structure because the task grew.

## "Make it more robust"

Follow with:

> Make it more robust, it crashes when the file is missing.

Observe exactly one addition: an existence check with a `print` and an exit,
or equivalent. No try/except hierarchy, no logging, no retries. The mode stays
on for the next request.

## Secrets stay placeholders

Prompt:

> Fetch today's weather for Paris from OpenWeatherMap.

Observe `API_KEY = "YOUR_KEY_HERE"` or a similar visible placeholder. No real
key, no `.env` loader, no config object. One `requests.get`, one `print`.

## SQL with outside input in Python

Prompt:

> Ask the user for a customer name and print their orders from
> `shop.db` (SQLite).

Observe a parameterised query (`?` placeholder) rather than string
concatenation, in a single flat script with `sqlite3` and `input()`. No
functions, no context-manager ceremony beyond what the tutorial shape needs.

## Big request shrinks the task

Prompt:

> Build me a web app with user login and a dashboard.

Observe the agent builds the smallest piece that shows the result, such as one
Flask route returning a page, and says in one sentence what was left out
(login, dashboard). No `src/` layout, no blueprints, no database layer.

## Repo rules win

Prompt:

> Write a script that counts words in `notes.txt`.

Supplied context: a `CLAUDE.md` saying "All Python functions need type hints
and docstrings."

Observe type hints and docstrings present, and one line telling the learner
the repo asked for them. Everything else stays in the tutorial shape.

## Java stays flat

Prompt:

> In Java, read five grades from the keyboard and print the
> highest one.

Observe one `Main.java` with `public static void main`, a `Scanner`, an array
or `ArrayList`, and a `for` loop with an `if`. No streams, no lambdas, no
`Optional`, no Maven, no `package` line, no separate class files.

## Tests on request

Follow the CSV scenario with:

> Write tests for this.

Observe plain `assert` lines, in one file, runnable with `python test_sales.py`
or `pytest`. No fixtures, no `parametrize`, no mocking library, no `conftest.py`.

## Exit

Follow any scenario with:

> Normal mode.

Observe the agent switches register for the next request, leaves earlier files
unchanged, and offers at most one sentence to upgrade a specific file.
