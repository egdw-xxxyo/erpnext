# Release notes (Примітки до випуску)

One markdown file per release, named by version: `v2026.07.13.md` (matches the
git tag). Written in Ukrainian.

Format:
- First `# Heading` line → release title.
- Everything after → body (rendered to HTML).
- Filename stem (`v2026.07.13`) → version; the date is parsed from it.

On every `./deploy migrate` the `after_migrate` hook
(`erpnext.manufacturing.doctype.release_note.release_note.sync_release_notes`)
reads these files and upserts a **Release Note** DocType record for each, so the
changelog is visible in the UI (`/app/release-note`). Files are the source of
truth — edits to a doc are overwritten from its file on the next sync.

When finishing a feature or bugfix, add/update the file for the current release.
