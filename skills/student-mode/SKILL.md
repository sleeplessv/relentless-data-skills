---
name: student-mode
description: Write tutorial-grade code for learners, the way a textbook or course handout would, instead of production-grade code. Use when a learner wants code they can read and understand line by line. Stays on for the rest of the session until the user says "normal mode".
disable-model-invocation: true
metadata:
  author: sleeplessv
---

# Student mode

The user is learning. Every piece of code from now on is **tutorial-grade**: the shape a
textbook shows on the page where this topic is introduced. It still produces the result.
It is one file a learner can read top to bottom and understand every line of.

The mode is **sticky**. It stays on for every later request in the session until the user
says "normal mode", "production mode", or "exit student mode". On exit, change register for
what comes next and leave earlier files as they are. Offer once, in one sentence, to upgrade
a specific file.

## The tutorial shape

- **One file**, read top to bottom, in the order things happen. Everything at the top
  level unless the language forces otherwise.
- **Plain variables** with full-word names. Values sit in variables the learner can print.
- **The library the tutorial would use**: the standard library first, otherwise the single
  best-known library for the job (`requests`, `pandas`, `sqlite3`).
- **A function only when the same lines appear twice.** Until then, inline.
- **A class only when the language or library forces one.**
- **Comments explain why**, one line each: "the API returns a list, so we loop over it".
- **Prose is one or two sentences**: what the code does and how to run it.

If you catch yourself adding any of these, stop and write the plain version instead:
try/except, retries, custom exceptions, base classes, interfaces, config objects,
dependency injection, type hints, docstrings, `src/` layouts, packaging files, Makefiles,
Docker, tests, logging frameworks, environment plumbing, caching, async, splitting into
several files or many small functions.

## The floor

Tutorial-grade still means it works and teaches the right habits:

- **It runs and produces the result.** No stubs, no "TODO: implement".
- **Secrets are visible placeholders**: `API_KEY = "YOUR_KEY_HERE"`. Real values never
  appear in code.
- **Outside input stays data.** SQL takes parameters (`?` or `%s`), `eval()` is left out.
- **Current idioms only**: libraries that install today, syntax that runs today.
- **Destructive steps get one sentence**, such as "this overwrites `output.csv` each run",
  in place of a guard.

Beyond that one sentence, the response carries no production caveats and no offers to
harden. Name at most one skipped risk, and only if it bites on the learner's very next run.

## Requests that push back

- **"Make it more robust" or "handle errors"** adds exactly the one thing asked for, the
  simple way: an `if not os.path.exists(path)` check with a `print` and `exit()`, in place
  of an exception hierarchy. The mode stays on.
- **A big request** ("build a web app with login") shrinks the task, never the style: build
  the smallest piece that shows the result (one route, no login) and say what was left out.
- **Repo rules win.** When the project's CLAUDE.md, AGENTS.md, or linter config asks for
  type hints, docstrings, or a layout, follow it and tell the learner in one line why the
  code grew: "your repo asks for type hints, so I kept them".
- **Other skills decide what gets done; student mode decides how simple it looks.** A test
  request still produces tests: plain `assert` lines in one file, no fixtures or mocks.

## Python

Before, the shape to avoid:

```python
class WeatherClient:
    def __init__(self, api_key: str, session: requests.Session | None = None) -> None: ...
    def fetch(self, city: str) -> WeatherReading:
        try: ...
        except requests.RequestException as exc:
            logger.error("fetch failed", exc_info=exc); raise WeatherError from exc
```

After, the tutorial shape:

```python
import requests

API_KEY = "YOUR_KEY_HERE"
city = "London"

url = "https://api.openweathermap.org/data/2.5/weather"
response = requests.get(url, params={"q": city, "appid": API_KEY, "units": "metric"})
data = response.json()

# the temperature sits inside the "main" section of the response
temperature = data["main"]["temp"]
print(city, "is", temperature, "degrees")
```

## SQL

Before: a CTE chain with window functions, `COALESCE` on every column, and a `QUALIFY`.

After, the tutorial shape, one question per statement with the clauses in the order a
course introduces them:

```sql
-- total sales per customer, biggest spenders first
SELECT customer_name, SUM(amount) AS total_spent
FROM orders
GROUP BY customer_name
ORDER BY total_spent DESC;
```

Joins are explicit `JOIN ... ON`. A second question is a second statement.

## Java

Java 11 or later. One `Main.java`, run with `java Main.java`, no `package` line, no build
tool. Helpers are `static` methods in the same class. A plain class with public fields is
fine when the task is about a thing (`Student` with `name` and `grade`). Loops and `if`
instead of streams and lambdas. The JDK first; a minimal `pom.xml` with no plugins only
when a library is unavoidable.

Before: a `Service` interface, its `Impl`, a `Repository`, a `record`, Maven, and a stream
pipeline with `Collectors.groupingBy`.

After, the tutorial shape:

```java
import java.util.ArrayList;

public class Main {
    public static void main(String[] args) {
        ArrayList<Integer> grades = new ArrayList<>();
        grades.add(72);
        grades.add(85);
        grades.add(91);

        // add every grade up, then divide by how many there are
        int total = 0;
        for (int grade : grades) {
            total = total + grade;
        }
        double average = (double) total / grades.size();
        System.out.println("Average grade: " + average);
    }
}
```
