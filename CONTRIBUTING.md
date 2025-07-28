# 💖 Contributing to Boosty Downloader

Hello, I'm glad you find this project useful and I appreciate your willingness to contribute.

I created this note to help you understand the way you can help improve the project.


## 👩‍💻 Development Process

<div align="center">
<img src="/assets/dev-process.svg" height="400" alt="Development Process" style="border-radius: 12px;">
</div>

### 🔧 Quick Start

1. Fork and clone the repository
2. Install dependencies: `poetry install`
3. Create a feature branch and make your changes
4. Run tests: `poetry run pytest`
5. Don't forget version bump `poetry version patch` (or minor/major) and update `CHANGELOG.md`
6. Open a pull request and describe changes and why they are needed

**Most of needed/handy commands are available via `make`.**
To see available commands, run:
```bash
make help
```

### 🩺 Code Quality

We use:
- **Ruff** for linting and formatting
- **Pyright** for type checking
- **pytest** for testing

*Please ensure your IDE is configured to use these tools for a smooth development experience.*


### 📝 Writing Good Commit Messages

**We use**:
- [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) for commit messages.
- [GitMoji](https://gitmoji.dev/) for visual representation of commit types. (**OPTIONAL**)
- Describe not only the change but also **why** it was made.


So a generic commit message would look like this:
```
feat: ✨ Add hyperspace drive support
         The hyperspace drive allows faster travel between galaxies.

fix: 🐛 Fix formatting.
```

**To make it even easier for you, use VS Code extension:** 
- [VSCode Conventional Commits](https://marketplace.visualstudio.com/items?itemName=vivaxy.vscode-conventional-commits) - it speed up writing commit messages in our format.


### ✅ Pull Requests CI Checks

**Now project uses Github Actions for:**
- Check PRs for code quality (linting, type checking, tests)
- Check `dev -> main` PRs for version bump 
- Automatically create releases on `main` merge (PyPi and GitHub Releases)


### 🔨 Other HOW TOs:

<details>
<summary>🏁 Making a Release</summary>

1. **Prepare in `dev` branch:**
   ```bash
   poetry version patch  # or minor/major
   # Update CHANGELOG.md
   git commit -am "chore: bump version to X.Y.Z"
   git push origin dev
   ```

2. **Create PR:** `dev` → `main`

3. **Merge PR** → Automatic release! 🎉
</details>

<details>
<summary>🐛 Hotfix</summary>

1. **From main:**
   ```bash
   git checkout -b hotfix/fix-name
   poetry version patch
   # Fix bug, update changelog
   ```

2. **PR:** `hotfix/*` → `main`
</details>
