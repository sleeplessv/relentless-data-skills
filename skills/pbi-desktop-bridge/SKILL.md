---
name: pbi-desktop-bridge
description: Reload Power BI Desktop and screenshot report pages from a Mac, with Desktop running in a Parallels Windows VM, so an edit to PBIP files (report pages, visuals, theme, measures) is seen rendered. Use when a PBIP edit made on a Mac needs checking in Power BI Desktop, or when a screenshot of a report page from Desktop is wanted.
---

# pbi-desktop-bridge

Run the **edit loop** from the Mac: edit PBIP files, push them into the Power BI Desktop running in the
Parallels VM, and read a screenshot of the result. Every call goes through
`<skill-dir>/scripts/pbi-vm.sh` (`<skill-dir>` is this skill's directory), run from inside the project.
Its exit code is the result: 0 done, 3 a **refusal**, the rest in `pbi-vm.sh --help`.

## Check the VM is ready

```bash
<skill-dir>/scripts/pbi-vm.sh status
```

Ready means the JSON lists one instance whose `currentFilePath` is the `.pbip` you are editing
(`\\Mac\Home\` is the Mac home folder). For any other result, follow [setup](references/setup.md).

The wrapper keeps its state and screenshots in `.pbi-desktop/` at the repo's top level. Keep that folder
out of git. From the top level:

```bash
git check-ignore -q .pbi-desktop || echo '.pbi-desktop/' >> "$(git rev-parse --git-path info/exclude)"
```

`git check-ignore -q` exits 0 when the folder is already ignored, and the line is then left alone. On
exit 1 the folder joins this clone's local exclude file, which is never committed.

## The edit loop

1. **Check before you edit.** `pbi-vm.sh safe-reload --check` reloads nothing. Exit 0: a push will go
   through. Exit 3 is a refusal: Desktop holds unsaved work that is the user's. Ask them to save in Desktop
   (Ctrl+S) and run the check again, so their save lands before your edit and never over it.
2. **Edit** the files of the project Desktop has open.
3. **Dry-run a model edit** (a report-only edit goes straight to step 4):

   ```bash
   <skill-dir>/scripts/pbi-vm.sh sync-model
   ```

   Done when `changes` lists every measure you edited and no other. Any other entry is a measure that
   differs for a reason you did not create, and step 4 would replace Desktop's version of it: stop and
   show the user the list. A measure you edited that `changes` leaves out has an edit `--model` cannot
   carry: it reaches Desktop the way the last row of the table below says.
4. **Push.** `pbi-vm.sh safe-reload` for a report-only edit, `pbi-vm.sh safe-reload --model` after a
   measure edit. Done on exit 0. A refusal here means the user worked in Desktop after step 1. Their save
   is the one way past it, and it can write Desktop's version over the files you edited: after they save,
   read `git diff`, make again whatever part of your edit is gone, and go back to step 3.
5. **Look.** `pbi-vm.sh shot <page-id> <run>` prints the path of a PNG: read the image. `<page-id>` is
   the page's folder name under `definition/pages/`, and `<run>` is any label for this round.
   `pbi-vm.sh shots <run>` takes every page. Done when the screenshot shows the edit.

A screenshot proves the edit landed. Whether the numbers are right is a separate check against the
source data.

## What reaches Desktop

| Edit | How it reaches Desktop |
|---|---|
| Report pages, visuals, theme (PBIR) | `safe-reload` |
| Measures: add, change, remove | `safe-reload --model` |
| Columns, tables, relationships, Power Query | The user clicks "Apply external changes" in Desktop (the banner shows after they save), or reopens the project |

`--model` compares measures and table names, nothing else. After any other model edit, exit 0 tells you
the report reloaded while the model edit is still outside Desktop: ask the user for the banner click
before step 5.

## When the screenshot shows the old value

- A measure edit shows in Desktop 10 to 20 seconds after the push. Take the shot once more, with
  `PBI_SETTLE_MS=20000` in front of the command.
- A visual keeps the result of its last query. A model edit that arrived through the user's banner click
  can stay hidden behind that cached result until the visual's query changes, for example when the user
  clicks a slicer. A `--model` push clears the cache.
- In a `shots` run the first page can be captured before it renders. Retake that page with `shot`.

Still old after these: the edit did not land. Go back to the step 3 output and the table above.

## Hand back to the user

- **Save first.** A reload leaves Desktop marked as unsaved, and the next reload replaces whatever the
  user changed in Desktop since. Tell the user to save in Desktop (Ctrl+S) before they work there and
  before they ask for the next edit.
- **A save rewrites the project.** Desktop's save touches files you did not edit: schema versions,
  `cultures/` synonyms, annotations, saved slicer state and, after a refresh, column data types. Show the
  user `git status` in two groups: the files you edited, and the rest as Desktop's changes. A commit the
  user asks for takes the first group.
- **Data is the user's.** Data source sign-in and refresh happen in Desktop, by the user.
