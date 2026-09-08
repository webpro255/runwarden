# Release checklist for v0.1.0

Every command here is run by David, by hand, in this order. Nothing in this list
was executed by the builder session that wrote it, and nothing in it belongs in
CI. The repository is private and named after the working name at the time this
was written, so the rename and the visibility flip come before anything public.

Assumes `feature/phase3` has been reviewed and merged to `main`, and that the
working directory is the repo root.

## 1. Rename the repository on GitHub

```
gh repo rename runwarden
```

Run this from inside the local clone. Two things follow automatically: GitHub
serves a redirect from the old URL, so any link already shared keeps working,
and the local `origin` remote is rewritten to the new name, so no
`git remote set-url` is needed. Confirm both:

```
git remote -v
gh repo view --json name,url
```

Renaming the local folder is optional and affects nothing:

```
cd .. && mv runprobe runwarden && cd runwarden
```

## 2. Set the description and homepage

```
gh repo edit webpro255/runwarden \
  --description "Detect undeclared cross-run communication channels in autonomous AI agent environments" \
  --homepage "https://github.com/webpro255/runwarden"
```

The description is the same tagline as the README H1 subtitle and the pyproject
`description`. Keep the three in step; it is the string that shows up in GitHub
search results and in the social preview card.

## 3. Add the topics

Topics mirror the pyproject keywords, lowercase and hyphenated. GitHub allows at
most 20; this is 12.

```
gh repo edit webpro255/runwarden \
  --add-topic ai-agents \
  --add-topic ai-agent-security \
  --add-topic ai-security \
  --add-topic llm-security \
  --add-topic agent-isolation \
  --add-topic sandbox-escape \
  --add-topic cross-run \
  --add-topic noninterference \
  --add-topic information-flow \
  --add-topic covert-channel \
  --add-topic multi-agent \
  --add-topic security-testing
```

Verify:

```
gh repo view webpro255/runwarden --json repositoryTopics
```

## 4. Fill the two placeholders

Both are deliberate TODOs left by the builder. Neither can be guessed correctly
by anyone but you.

- `CITATION.cff`, the `date-released` field. It currently reads `2026-01-01`
  under a TODO comment. Set it to the actual release date in `YYYY-MM-DD` form,
  and delete the TODO comment line.
- `SECURITY.md`, the string `TODO-SECURITY-CONTACT`. Replace it with the address
  you want vulnerability reports on, or delete that bullet entirely and rely on
  the private advisory link above it.

Then confirm nothing was missed:

```
grep -rn "TODO" CITATION.cff SECURITY.md
```

Commit both on `main` before tagging, so the tag contains the real date.

## 5. Flip the repository public

Settings, General, Danger Zone, Change visibility, Make public. Or:

```
gh repo edit webpro255/runwarden --visibility public --accept-visibility-change-consequences
```

Before flipping, confirm nothing private is tracked. `PLAN.md` and `.prompts/`
are gitignored and must stay that way:

```
git ls-files | grep -E "PLAN.md|^\.prompts/"     # must print nothing
git log --all --format=%B | grep -c Co-Authored  # must print 0
```

After flipping, check that the CI badge in the README resolves, since a badge
for a private repo renders as unknown.

## 6. Tag and release

```
git checkout main
git pull origin main
pytest -q
ruff check .

git tag -a v0.1.0 -m "runwarden 0.1.0"
git push origin v0.1.0

gh release create v0.1.0 \
  --title "runwarden 0.1.0" \
  --notes-file <(sed -n '/^## \[0.1.0\]/,/^## \[/p' CHANGELOG.md | head -n -1)
```

If the `--notes-file` substitution is awkward in your shell, paste the 0.1.0
section of `CHANGELOG.md` into `gh release create v0.1.0 --notes-file -` or just
use `--generate-notes` and edit afterwards.

## 7. Publish to PyPI

`build` and `twine` are not project dependencies and must not be added as any.
Install them into a throwaway environment:

```
python3 -m venv /tmp/pubenv
/tmp/pubenv/bin/pip install build twine
```

Build from a clean tree, so no stale artifact is uploaded:

```
rm -rf dist/
/tmp/pubenv/bin/python -m build
/tmp/pubenv/bin/twine check dist/*
```

`twine check` must pass on both the wheel and the sdist before anything is
uploaded.

One thing to look at specifically on the TestPyPI page below: the license.
`pyproject.toml` declares `license = "Apache-2.0"` as a PEP 639 SPDX expression
and deliberately carries no `License :: OSI Approved :: Apache Software License`
classifier, because the two are specified as mutually exclusive and PyPI is the
place that enforces it. Hatchling and `twine check` both accept the classifier
if it is added, so this could only be settled on the server. If the TestPyPI
page shows the license correctly, which is the expected outcome, nothing needs
changing.

Do the TestPyPI dry run first. It is the only way to see the rendered page
before the real name is spent, and a PyPI version number cannot be reused once
uploaded:

```
/tmp/pubenv/bin/twine upload --repository testpypi dist/*
```

Look at https://test.pypi.org/project/runwarden/ and check the README rendered,
the description line, the classifiers, the license, and the four project links
in the sidebar. Then install it from there into a scratch venv and run it once:

```
python3 -m venv /tmp/checkenv
/tmp/checkenv/bin/pip install --index-url https://test.pypi.org/simple/ runwarden
/tmp/checkenv/bin/runwarden --version
/tmp/checkenv/bin/runwarden probe --config examples/surfaces.json
```

Only then, the real upload:

```
/tmp/pubenv/bin/twine upload dist/*
rm -rf dist/
```

Push to GitHub before publishing to PyPI, never the other way around. The tag in
step 6 comes first.

## 8. After publish

- Open https://pypi.org/project/runwarden/ and read the rendered README on the
  page itself. It is the package storefront and it renders differently from
  GitHub: check the tables, the fenced code blocks, and that the badge row is
  not broken. Relative links such as `LIMITATIONS.md` do not resolve on PyPI,
  so if any of them matter there, they need absolute GitHub URLs in a follow up.
- Check the GitHub social preview card, Settings, General, Social preview. With
  no image uploaded GitHub generates one from the repo name and description, so
  confirm the description reads well in that card.
- Install from real PyPI into a clean venv and run the fixture once, as the
  final confirmation that what was published is what was tested:

```
python3 -m venv /tmp/finalcheck
/tmp/finalcheck/bin/pip install runwarden
/tmp/finalcheck/bin/runwarden probe --config fixtures/artifactory_mailbox/surfaces.json
```

- Confirm the `Changelog` project URL on the PyPI sidebar resolves, since it
  points at a `main` path that only exists once the repo is public.
