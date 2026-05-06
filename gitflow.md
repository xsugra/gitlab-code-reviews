## Git flow strategy for this repository

Use a lightweight **Git Flow (GitHub-hosted)** model:

### Branches

- `main`: production-ready, protected branch.
- `develop`: integration branch for next release.
- `feature/<short-name>`: new work (branch from `develop`).
- `fix/<short-name>`: non-urgent bug fixes (branch from `develop`).
- `release/<version>`: stabilization before release (branch from `develop`).
- `hotfix/<short-name>`: urgent production fixes (branch from `main`).

### Day-to-day workflow

1. Create branch from `develop`:
   ```bash
   git checkout develop
   git pull
   git checkout -b feature/webhook-hardening
   ```
2. Commit in small units (clear messages).
3. Open PR into `develop`.
4. Require review + passing checks before merge.

### Release workflow

1. Create `release/x.y.z` from `develop`.
2. Only stabilization fixes on release branch.
3. Merge release branch into `main` and tag (`vX.Y.Z`).
4. Merge same release branch back into `develop`.

### Hotfix workflow

1. Create `hotfix/<name>` from `main`.
2. Open PR to `main` and merge after review.
3. Merge hotfix back into `develop` to keep branches aligned.

### GitHub repository setup recommendations

For `xsugra/gitlab-code-reviews`:

- Protect `main` and `develop`.
- Require pull requests (no direct pushes).
- Require at least 1 approval.
- Require status checks before merging.
- Enable squash merge (clean history).

### Connect local project to your GitHub repo

```bash
git remote add origin git@github.com:xsugra/gitlab-code-reviews.git
# or
git remote add origin https://github.com/xsugra/gitlab-code-reviews.git
```
