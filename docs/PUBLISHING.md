# Publishing to GitHub

The repository source is prepared for GitHub. Generated data, credentials, reports,
models, backups, and the local Power BI project are excluded by `.gitignore`.

## Before making the repository public

1. Choose a repository name and visibility.
2. Choose a license. No license is included, so the default copyright rules apply until
   the owner deliberately adds one.
3. Review the staged file list with `git status`.
4. Create the initial commit using your own Git identity.
5. Create an empty GitHub repository and add it as the remote.

```powershell
git config user.name "Your Name"
git config user.email "your-public-or-noreply-address"
git commit -m "Initial MarketPulse AI release"
git remote add origin <your-repository-url>
git push -u origin main
```

Do not paste credentials into Git commands, issues, documentation, or workflow files.
GitHub Actions runs the offline lint and test suite on Windows. Live pipeline checks need
a private PostgreSQL instance and generated data and are intentionally not part of CI.

The generated Power BI project is rebuilt locally after the first successful pipeline
run because its semantic model contains a machine-specific path. The builder and report
definition logic are included in `scripts/build_powerbi.py`.
