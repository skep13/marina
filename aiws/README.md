# the AI workstation

A Debian 13 workstation for AI-assisted development: an i3 desktop,
one authenticated API over every model, project workspaces that come
back as you left them, an assistant that can see and use the desktop
with a visible action history and a stop button, and jobs that run on
other machines in the homelab. Marina is one of the apps it runs.

* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): what was measured, the
  choices and why, the lab3 memory budget, migration options
* [docs/PLAN.md](docs/PLAN.md): first-release scope, phases, the
  milestone demo, the experiments queue

## Layout

| path | what |
|---|---|
| `src/aiws/` | aiwsd (gateway, models, projects, jobs, cluster), the CLI, the assistant, desktop glue, Control Centre UI |
| `tools/` | `ai-bench` (TTFT, prompt/gen speed), `ai-mem` (PSS by group + GPU) |
| `pkg/aiws-core/` | systemd units, slices, desktop files that ship in aiws-core |
| `build/` | live-build definition, package scripts, pinned versions, branding |
| `examples/demo/` | a small project with a bug, for the demo |
| `bench/results/` | benchmark JSON, one file per run |
| `tests/` | `python -m unittest discover -s aiws/tests` |

## Build the ISO

On a Debian 13 machine (the `quay-build` container, lab2 ct120):

```bash
rsync -a aiws/ root@quay-build:/srv/aiws/
ssh root@quay-build /srv/aiws/build/build.sh
```

`REPRODUCIBLE=1` builds from snapshot.debian.org at the date in
`build/versions.env`; llama.cpp and llama-swap are pinned there too.
Each build writes the ISO, its sha256 and the full package manifest to
`build/out/`.

## Run aiwsd from a checkout

```bash
cd aiws/src
AIWS_ETC=../build/config/includes.chroot/etc/aiws AIWS_STATE=/tmp/aiws \
  python -m aiws.server
AIWS_TOKEN_FILE=/tmp/aiws/desktop.token python -m aiws.cli status
```
