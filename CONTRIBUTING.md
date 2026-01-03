# 💖 Contributing to Boosty Downloader

Hello, I'm glad you find this project useful and I appreciate your willingness to contribute.

I created this note to help you understand the way you can help improve the project.


## 👩‍💻 Development Process

This project uses **trunk-based development** — all changes go directly to `main` via short-lived feature branches and pull requests.

### 🔧 Quick Start

1. Fork and clone the repository
2. Install dependencies: `poetry install`
3. Create a branch from `main` using one of these prefixes:
   - `feat/` - new features (`feat/add-download-resume`)
   - `fix/` - bug fixes (`fix/corrupted-video-output`)
   - `refactor/` - code improvements (`refactor/simplify-api-client`)
   - `docs/` - documentation (`docs/update-readme`)
   - `chore/` - maintenance tasks (`chore/update-dependencies`)
4. Run tests: `poetry run pytest`
5. Open a pull request to `main` and describe changes and why they are needed

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

**Project uses Github Actions for:**
- Check PRs for code quality (linting, type checking, tests)
- Automatically create releases when version tags are pushed (PyPI and GitHub Releases)


### 🔨 Other HOW TOs:

<details>
<summary>🏁 Making a Release (Maintainers)</summary>

1. **Bump version and update changelog:**
   ```bash
   poetry version patch  # or minor/major
   # Update CHANGELOG.md with the new version
   git commit -am "chore: bump version to X.Y.Z"
   git push
   ```

2. **Tag and push:**
   ```bash
   git tag v$(poetry version -s)
   git push --tags
   ```

3. **Automatic release!** 🎉 (PyPI + GitHub Release)
</details>
