# Releasing agent-core to PyPI

`agent-core` is published to PyPI with **Trusted Publishing (OIDC)** by the
`.github/workflows/release.yml` workflow. No PyPI API token or long-lived secret
is stored in this repository: GitHub mints a short-lived OIDC token at publish
time and PyPI verifies it against a publisher you register once.

## One-time setup (maintainer, on pypi.org)

Because `agent-core` does not exist on PyPI yet, register a **pending
publisher** so the first tagged release can create the project:

1. Sign in to <https://pypi.org> and open **Your account -> Publishing**
   (<https://pypi.org/manage/account/publishing/>).
2. Under **Add a new pending publisher**, fill in:
   - **PyPI Project Name:** `agent-core`
   - **Owner:** `pdz1804`
   - **Repository name:** `agentforge`
   - **Workflow name:** `release.yml`
   - **Environment name:** `pypi`
3. Save. (After the first successful publish this becomes a normal trusted
   publisher for the created project.)

Optional hardening: in the GitHub repo, create an **Environment** named `pypi`
(**Settings -> Environments**) and add required reviewers so a publish waits for
manual approval. The workflow already targets `environment: pypi`.

## Cutting a release

1. Make sure `packages/agent-core/pyproject.toml` `version` is the version you
   intend to publish (currently `0.1.2`).
2. Tag the release and push the tag. The tag MUST be `v<version>` (the build job
   fails if the tag does not match the pyproject version):

   ```bash
   git tag v0.1.2
   git push origin v0.1.2
   ```

3. `release.yml` runs:
   - **build** builds the sdist + wheel, verifies the tag matches the pyproject
     version, and runs `twine check`.
   - **publish** uploads to PyPI via Trusted Publishing (`skip-existing: true`,
     so re-running an already-published tag is a no-op).
4. Confirm at <https://pypi.org/project/agent-core/> and test:

   ```bash
   pip install agent-core
   ```

You can also trigger the workflow manually from the Actions tab
(`workflow_dispatch`) to rehearse the build/validate steps without tagging.

## What CI checks on every push

`.github/workflows/ci.yml` also builds and validates the distribution on every
push (`package-build` job: `python -m build` + `twine check` + a clean-venv
import of the built wheel), so a broken README, classifier, or package layout is
caught long before tag time. A `security-audit` job runs `pip-audit` and
`bandit` in advisory mode.
