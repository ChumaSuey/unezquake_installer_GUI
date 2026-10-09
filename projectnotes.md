# Project Notes — Ideas & Concepts (not implemented)

This file holds design notes and ideas for the unezquake Installer that are **not
implemented yet**. Treat everything here as a concept, not a promise.

---

## Concept: "Quick client installer" (fallback download from GitHub)

**Status:** IMPLEMENTED on Windows/macOS (2026-10-09).

The prebuilt-release path is now the normal **Update** action on Windows/macOS
(`backend.ReleaseInstallWorker`): it downloads the matching asset from the latest
GitHub release and extracts the client into the Install location. The notes below
are kept as the original design rationale. Still open: offering the same download
on Linux alongside the source build, and checksum/signature verification.

### The problem

The normal **Update** flow clones the repository, updates submodules, runs
`build-linux.sh`, and installs the compiled binary. That is the right way to get
the latest source build, but it has downsides:

- It needs a full build toolchain (git, gcc, cmake, make) and time.
- It is **Linux-only**; Windows/macOS users cannot build it here.
- Sometimes someone needs a **specific feature, fix, or version** that is only
  available as a prebuilt release, not as a source build.

### The idea

Add an optional **"Quick install from GitHub"** path that downloads a client
binary directly from a project's GitHub **releases**, without cloning or
building. It would be an *in-case* alternative to Update.

Rough flow:

1. Pick the client/repository (e.g. unezquake, or a QuakeWorld client such as
   ezQuake).
2. Query the GitHub Releases API for the latest (or a chosen) release.
3. Choose the asset that matches the current OS/architecture (a Linux binary, a
   Windows `.zip`, etc.).
4. Download it into the chosen install directory.
5. Verify it if a checksum is published.
6. Mark the install as **"downloaded / manually managed"** so Update knows it did
   not come from a local source build.

### Why it is useful

- Works on platforms where building is not supported (e.g. Windows).
- Much faster for users who just want a working client.
- Lets people grab a specific release when a special feature/fix is needed.

### Open questions / things to decide

- **Which repositories?** Only unezquake, or any client (ezQuake, etc.)? The
  installer is unezquake-focused today.
- **Assets:** release asset naming varies a lot; need reliable OS/arch matching
  and a sensible "pick manually" fallback.
- **Checksums/signing:** only trust releases that publish verification data.
- **GitHub API rate limits / authentication:** anonymous requests are limited;
  a token may be needed for frequent checks.
- **Licensing:** the downloaded binaries keep their own license; make that clear.
- **Interaction with Find/Update:** how a downloaded install coexists with the
  source build (versions, which one "Update" targets).
- **Windows/macOS:** which clients even ship prebuilt desktop binaries.

### Relation to current features

- **Find current install** already locates existing installs and reports their
  engines and data library. A quick installer would complement it by giving a way
  to obtain a client when none (or only an outdated one) is found.
- **Update** remains the source-build path; the quick installer would be a
  separate, explicit option.

---

## Other small ideas

- Optionally verify a found install's engine version/build.
- Remember the last found/used install between sessions.
