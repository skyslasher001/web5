# Proposal: CI can't find `astral-sh/setup-uv@v10`

Status: **applied 2026-10-27** (owner-approved: "apply"). The first run caught that the line had two spaces before its comment, which prettier rejects; it was reformatted to one (same line, same pin).

Patch: [`ci-setup-uv-version.patch`](ci-setup-uv-version.patch). It changes one line in `.github/workflows/ci.yml`,
which is protected (CI config).

## The problem

GitHub now gives CI jobs a runner. They used to end with no runner at all, an account problem that is fixed now.
Both jobs (Ubuntu and Windows) then fail in GitHub's own "Set up job" step, before any of our steps run:

```
##[error]Unable to resolve action `astral-sh/setup-uv@v10`, unable to find version `v10`
```

That was run 39903140596, attempt 2, on `0f6df61`, 2026-10-27. `astral-sh/setup-uv` publishes floating
major-version tags only up to `v7`. From `v8` on it publishes only full versions (`v10.0.0` … `v10.3.2`), so
`@v10` matches nothing. The other actions in the workflow (`actions/checkout@v6`, `actions/setup-node@v6`,
`actions/upload-artifact@v7`) do have those tags.

## The fix

Pin the exact latest release, `astral-sh/setup-uv@v10.3.2` (tag commit `07a047e`). Nothing else changes; the
workflow passes no inputs to it.

## What was run

- `git ls-remote --tags https://github.com/astral-sh/setup-uv` (2026-10-27): the major tags stop at `v7`;
  `v10.3.2` is the newest release tag.
- The patched workflow parses as YAML, and `git apply --check` passes on the branch head `0f6df61`.
- GitHub Actions itself can't be run from here. After you apply it, the next push runs CI. This is also the first
  time anything will run on Windows, so more failures may show up behind this one; they'll be fixed as they come.

## To apply it

```sh
git apply docs/proposals/ci-setup-uv-version.patch
git add -A && git commit -m "Apply the ci-setup-uv-version patch"
git push
```
