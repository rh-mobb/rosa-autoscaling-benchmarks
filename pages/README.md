# GitHub Pages landing template

This directory holds **`index.html`**, the home page for the static site deployed by **`.github/workflows/deploy-github-pages.yml`**.

- **`__GITHUB_REPO_URL__`** is replaced at deploy time with `https://github.com/<owner>/<repo>` (via `sed` and the `REPOSITORY` env var), so forks get the correct GitHub link automatically.
- Relative links **`simulator/`** and **`deck/`** resolve under the project Pages root (`https://<owner>.github.io/<repo>/`).

Do not commit secrets here; the file is public HTML only.
