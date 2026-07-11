# Releasing agent-core to PyPI

The package is published to PyPI under the distribution name **`pdz-agent-core`**
(imported as `agent_core`) with **Trusted Publishing (OIDC)** by the
`.github/workflows/release.yml` workflow. No PyPI API token or long-lived secret
is stored in this repository: GitHub mints a short-lived OIDC token at publish
time and PyPI verifies it against a publisher you register once.

> Why `pdz-agent-core` and not `agent-core`? PyPI blocks `agent-core` as "too
> similar to an existing project" (`agentcore`). The distribution name differs
> from the import name on purpose; installers run `pip install pdz-agent-core`
> but code still does `import agent_core`.

## One-time setup (maintainer, on pypi.org)

Because `pdz-agent-core` does not exist on PyPI yet, register a **pending
publisher** so the first release can create the project:

1. Sign in to <https://pypi.org> and open **Your account -> Publishing**
   (<https://pypi.org/manage/account/publishing/>).
2. Under **Add a new pending publisher**, fill in exactly:
   - **PyPI Project Name:** `pdz-agent-core`
   - **Owner:** `pdz1804`
   - **Repository name:** `agentforge`
   - **Workflow name:** `release.yml`
   - **Environment name:** `pypi`
3. Save. (After the first successful publish this becomes a normal trusted
   publisher for the created project.)

All five fields must match the OIDC token GitHub sends, or the publish fails
with `invalid-publisher`. The `Environment name` field in particular must be
`pypi` (the workflow runs in that environment).

## Publishing 0.1.2 (the PyPI debut)

The `v0.1.2` tag already exists from an earlier GitHub Release and predates this
workflow, so a tag push will not run `release.yml`. For this first PyPI publish,
trigger the workflow manually on `main` (its `agent_core` source is identical to
the tagged commit, and the tag/version guard self-skips on a non-tag ref):

```bash
gh workflow run release.yml --repo pdz1804/agentforge --ref main
```

Then confirm at <https://pypi.org/project/pdz-agent-core/> and test:

```bash
pip install pdz-agent-core   # then: python -c "import agent_core; print(agent_core.__version__)"
```

## Cutting future releases (0.1.3+)

1. Bump `version` in `packages/agent-core/pyproject.toml`.
2. Tag `v<version>` and push it (the build job fails if the tag does not match
   the pyproject version):

   ```bash
   git tag v0.1.3
   git push origin v0.1.3
   ```

3. `release.yml` runs **build** (sdist + wheel, tag/version guard, `twine
   check`) then **publish** (Trusted Publishing, `skip-existing: true`).

## What CI checks on every push

`.github/workflows/ci.yml` also builds and validates the distribution on every
push (`package-build` job: `python -m build` + `twine check` + a clean-venv
import of the built wheel), so a broken README, classifier, or package layout is
caught long before release time. A `security-audit` job runs `pip-audit` and
`bandit` in advisory mode.
