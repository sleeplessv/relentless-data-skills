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

Observe one Python file, read top to bottom, that reads the file with
`pd.read_csv` and totals it with a `groupby`. There is no `csv` module, no
loop over rows, and no functions, classes, try/except blocks, type hints, or
`if __name__ == "__main__"` guard. Comments say why, not what. The prose is
brief and does not mention what production code would add.

## Maths stays in NumPy and pandas

Follow the CSV scenario with:

> What is the median amount, and how many sales are above it?

Observe a `np.median` or `.median()` call and a boolean mask on the DataFrame,
each result in a named variable. There is no sorting by hand, no `statistics`
module, and no loop that counts rows.

## Sticky across requests

Follow the CSV scenario with:

> Now also show the average amount per region.

Observe that the code stays in the same single-file shape. The agent does not
refactor into functions or add structure because the task grew.

## "Make it more robust"

Follow with:

> Make it more robust, it crashes when the file is missing.

Observe exactly one addition, an existence check with a `print` and an exit
or equivalent. There is no try/except hierarchy, logging, or retry. The mode
stays on for the next request.

## Secrets stay placeholders

Prompt:

> Fetch today's weather for Paris from OpenWeatherMap.

Observe `API_KEY = "YOUR_KEY_HERE"` or a similar visible placeholder. There is
no real key, `.env` loader, or config object. The script makes one
`requests.get` call and one `print`.

## SQL with outside input in Python

Prompt:

> Ask the user for a customer name and print their orders from
> the SQLite file `shop.db`.

Observe a parameterised query with a `?` placeholder rather than string
concatenation, in a single flat script with `sqlite3` and `input()`. There
are no functions and no context managers beyond what the tutorial shape needs.

## Big request shrinks the task

Prompt:

> Build me a web app with user login and a dashboard.

Observe the agent builds the smallest piece that shows the result, such as one
Flask route returning a page, and says briefly what it left out, such as login
and the dashboard. There is no `src/` layout, blueprint, or database
layer.

## Repo rules win

Prompt:

> Write a script that counts words in `notes.txt`.

Supplied context: a `CLAUDE.md` saying "All Python functions need type hints
and docstrings."

Observe type hints and docstrings present, and a brief note telling the learner
the repo asked for them. Everything else stays in the tutorial shape.

## Java stays flat

Prompt:

> In Java, read five grades from the keyboard and print the
> highest one.

Observe one `Main.java` with `public static void main`, a `Scanner`, an array
or `ArrayList`, and a `for` loop with an `if`. There are no streams, lambdas,
`Optional`, Maven, `package` line, or separate class files.

## Tests on request

Follow the CSV scenario with:

> Write tests for this.

Observe plain `assert` lines, in one file, runnable with `python test_sales.py`
or `pytest`. There are no fixtures, `parametrize`, mocking library, or
`conftest.py`.

## Exit

Follow any scenario with:

> Normal mode.

Observe the agent writes the next request in the normal register, leaves
earlier files unchanged, and offers once, briefly, to upgrade a specific file.
