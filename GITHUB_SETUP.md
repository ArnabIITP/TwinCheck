# Publish TwinCheck to your private GitHub repository

The project files are ready locally. Create the empty remote repository once, then push this project.

## 1. Create the private repository

1. Open <https://github.com/new> while signed in to the intended GitHub account.
2. Set the repository name to `twincheck` (or your preferred name).
3. Choose **Private**.
4. Do **not** initialize it with a README, `.gitignore`, or license; these files already exist in this project.
5. Create the repository and copy its HTTPS URL.

## 2. Push this project

From the project root, run:

```bash
git remote add origin https://github.com/ArnabIITP/twincheck.git
git push -u origin main
```

Replace the remote URL if you chose a different owner or repository name. If the local `origin` already exists, inspect it with `git remote -v` before changing it.

If you are using the source-only ZIP rather than the Git-ready ZIP, initialize Git and commit before adding the remote:

```bash
git init -b main
git add .
git commit -m "feat: initial TwinCheck implementation"
git remote add origin https://github.com/ArnabIITP/twincheck.git
git push -u origin main
```

## 3. Verify the first push

- Confirm GitHub displays the repository as **Private**.
- Confirm the `CI` action runs successfully.
- Check the README demo command from a clean checkout.
- Keep test reports and real-world input corpora out of commits if they contain secrets or sensitive data.

## 4. Suggested first release workflow

Keep the repository private while you review the code, run CI and collect feedback from a few trusted testers. Before making it public, review the license, security policy, issue templates, contact path for vulnerabilities, repository metadata and all example outputs. Do not advertise the tool as a sandbox or as a proof of program equivalence.
