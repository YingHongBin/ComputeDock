#!/bin/bash

set -u
set -o pipefail

readonly AGENT_STATE_DIR="/var/lib/computedock-agent"
readonly AGENT_RUNTIME_DIR="/run/computedock-agent"
readonly SUPERVISOR_CONFIG="/etc/supervisor/supervisord.conf"
readonly DEFAULT_UID="1001"
readonly DEFAULT_GID="1001"

die() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 1
}

require_environment_variable() {
    local variable_name="$1"
    [[ -n "${!variable_name:-}" ]] \
        || die "Missing required environment variable: ${variable_name}"
}

require_environment_variable NEW_USER
require_environment_variable NEW_PWD
require_environment_variable COMPUTEDOCK_CONTAINER_NAME
require_environment_variable COMPUTEDOCK_INTERVAL

if [[ -z "${COMPUTEDOCK_TEST_OUTPUT:-}" ]]; then
    require_environment_variable COMPUTEDOCK_SERVER_URL
    require_environment_variable COMPUTEDOCK_TOKEN
fi

[[ "$NEW_USER" =~ ^[a-z][a-z0-9_-]*$ ]] \
    || die "NEW_USER must start with a lowercase letter and contain only lowercase letters, digits, underscores, and hyphens"

[[ "$COMPUTEDOCK_INTERVAL" =~ ^[0-9]+$ ]] \
    || die "COMPUTEDOCK_INTERVAL must be an integer between 5 and 3600"
(( ${#COMPUTEDOCK_INTERVAL} <= 4 )) \
    || die "COMPUTEDOCK_INTERVAL must be between 5 and 3600"
(( 10#$COMPUTEDOCK_INTERVAL >= 5 && 10#$COMPUTEDOCK_INTERVAL <= 3600 )) \
    || die "COMPUTEDOCK_INTERVAL must be between 5 and 3600"

if [[ "${COMPUTEDOCK_STATE_DIR:-$AGENT_STATE_DIR}" != "$AGENT_STATE_DIR" ]]; then
    die "COMPUTEDOCK_STATE_DIR is fixed to ${AGENT_STATE_DIR} in this image"
fi
export COMPUTEDOCK_STATE_DIR="$AGENT_STATE_DIR"

# Create the interactive user on first start. On a normal container restart the
# account already exists in the writable layer, so only its password is updated.
if ! id -u "$NEW_USER" >/dev/null 2>&1; then
    useradd -m -U -G sudo -s /bin/bash "$NEW_USER" \
        || die "Failed to create interactive user: ${NEW_USER}"
fi
interactive_uid=$(id -u "$NEW_USER") \
    || die "Cannot determine UID for interactive user: ${NEW_USER}"
interactive_gid=$(id -g "$NEW_USER") \
    || die "Cannot determine primary GID for interactive user: ${NEW_USER}"
if [[ "$interactive_uid" != "$DEFAULT_UID" || "$interactive_gid" != "$DEFAULT_GID" ]]; then
    die "Interactive user ${NEW_USER} must use UID:GID ${DEFAULT_UID}:${DEFAULT_GID}; got ${interactive_uid}:${interactive_gid}"
fi
printf '%s:%s\n' "$NEW_USER" "$NEW_PWD" | chpasswd \
    || die "Failed to set the password for ${NEW_USER}"

if [[ ! -f "/home/${NEW_USER}/.bashrc" ]]; then
    cp /etc/skel/.bashrc "/home/${NEW_USER}/.bashrc"
    chown "$NEW_USER:$NEW_USER" "/home/${NEW_USER}/.bashrc"
fi

if [[ ! -f "/home/${NEW_USER}/.bash_profile" ]]; then
    cp /etc/skel/.bash_profile "/home/${NEW_USER}/.bash_profile"
    chown "$NEW_USER:$NEW_USER" "/home/${NEW_USER}/.bash_profile"
fi

install -d -o root -g root -m 0755 /run/sshd
install -d \
    -o computedock-agent \
    -g computedock-agent \
    -m 0750 \
    "$AGENT_RUNTIME_DIR" \
    "$AGENT_STATE_DIR"
rm -f "${AGENT_RUNTIME_DIR}/agent.pid"

exec /usr/bin/supervisord -c "$SUPERVISOR_CONFIG"
