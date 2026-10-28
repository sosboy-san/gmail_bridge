# Docker Hub distribution and publishing

English · [日本語](DOCKER_RELEASE.md)

Repository: [sosboy/gmail-bridge](https://hub.docker.com/r/sosboy/gmail-bridge). Stable v1.1.1 adds IMAP timeout recovery to v1.1.0. Images support linux/amd64 and linux/arm64; ARM32 is unsupported.

## Install or upgrade

```bash
docker pull sosboy/gmail-bridge:1.1.1
```

Use docker-compose.config.image.example.yml for a new v1.1 installation, with exact BRIDGE_VERSION=1.1.1, one writable /config mount and BRIDGE_CONFIG_DIR=/config. Follow [Installation](INSTALL.en.md) for OAuth/configuration and safe waiting followed by explicit init. Existing deployments follow [Maintenance](MAINTENANCE.en.md): stop, complete backup, pull, stopped status, up; never repeat init. Keep legacy mounts when upgrading an older deployment before considering a separate layout change. v1.0 cannot use /config.

## Maintainer setup

Create the public Hub repository and a dedicated Read & Write access token (Delete is unnecessary). In GitHub environment dockerhub, set variables DOCKERHUB_USERNAME=sosboy and DOCKERHUB_NAMESPACE=sosboy, and secret DOCKERHUB_TOKEN. Never paste tokens into chat, code or logs.

## Release policy

.github/workflows/docker-publish.yml automatically runs only on v* tag pushes, not main pushes. Accepted formats are vMAJOR.MINOR.PATCH and vMAJOR.MINOR.PATCH-rc.N (MAJOR and N at least 1). It builds the selected tag's commit, not current main. Other prerelease formats are rejected.

| Git tag | Docker tags |
| --- | --- |
| v1.1.1 | 1.1.1 / 1.1 / 1 / latest |
| v1.1.0-rc.2 | 1.1.0-rc.2 only |

Each architecture is built and tested, including CLI startup, before one multiarch build/push. QEMU validation is not ARM hardware acceptance. Exact versions and published Git tags are never overwritten. RC publication does not update floating tags. Stable releases update minor/major/latest; latest can eventually cross major versions. Pull and container recreation apply updates, not merely restart.

Publication is serialized. Older stable releases are rejected to prevent floating-tag rollback; RC is rejected when a matching/newer stable exists. Supporting an older release line would require a reviewed floating-tag policy. Dependency/base-image refreshes require a new patch version, not rebuilding an immutable released version.

For the historical v1.0.0 bootstrap only, use Actions → Publish Docker release → Run workflow with its existing tag, because that tag predates the workflow. Manual dispatch still requires an existing accepted release tag and builds that commit.

## Verify publication

Check Actions Summary and all four stable tags:

```bash
docker buildx imagetools inspect sosboy/gmail-bridge:1.1.1
docker buildx imagetools inspect sosboy/gmail-bridge:1.1
docker buildx imagetools inspect sosboy/gmail-bridge:1
docker buildx imagetools inspect sosboy/gmail-bridge:latest
```

All must point to the published index digest with both architectures. If push partially fails, inspect existing tags/digests before choosing repair; never delete an exact version to bypass the overwrite guard. Update the Hub Overview from [DOCKER_HUB.md](DOCKER_HUB.md), which contains both language sections and navigation.
