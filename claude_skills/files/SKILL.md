---
name: files
description: Read, search, summarize, create, edit, rename, move, copy and delete files and folders in the working folder or in the user's attachments.
---

# Files

## Where to work

- Work only in the current working directory and in the folders you were
  given access to. Never touch files outside them.
- Resolve relative names against the current working directory.

## Look before acting

- Find files with Glob and search their contents with Grep before reading or
  changing them. Do not guess file names or paths.
- Read a file before editing it, and edit only the part the task requires.
- When several files match a vague request, ask the user which one with one
  short question instead of choosing.

## Changing files

- Use Edit for small changes to an existing file and Write for new files.
- Use Bash only for what the file tools cannot do, such as renaming, moving,
  copying or deleting files and folders, or creating folders. Keep each command
  simple and limited to the files the task names.
- Never overwrite an existing file unless the task asks for it. Choose a new
  name instead.
- Delete only files the user explicitly asked to delete. Never delete a folder
  recursively unless the user asked for that folder to be removed.
- Some actions need the user's permission. If permission is denied, stop that
  action and report what was not done. Do not try another way around it.

## Reporting

- Report what was read, created, changed, moved or deleted, using file names
  rather than full paths.
- Base every claim on what the tools actually returned.
