# industrial_ci local runner

Mirrors [`.github/workflows/build.yml`](../../.github/workflows/build.yml).

## Matrix

| distro | test_type |
|--------|-----------|
| humble | gcc, clang |
| jazzy | gcc, clang, gcc-asan, gcc-tsan |

## Usage

```bash
# One cell (same env as GitHub Actions)
./tools/industrial-ci/run-one.sh jazzy gcc

# Full matrix
./tools/industrial-ci/run-all.sh
```

Requires Docker. Uses the GitHub-hosted runner architecture (`linux/amd64`),
`ros:<distro>-ros-core`, Paho, Mosquitto, and
`ros-industrial/industrial_ci@master` with `ISOLATION=shell`.
