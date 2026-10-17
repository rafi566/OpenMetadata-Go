#!/usr/bin/env bash
# Source this file to select checkout-local tools and caches.
_om_env_init() {
    local script_dir checkout_root
    script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) || return 1
    checkout_root=$(CDPATH= cd -- "$script_dir/../.." && pwd -P) || return 1
    export OM_GO_ROOT="${OM_GO_ROOT:-$checkout_root/work/tools/go}"
    export OM_PYTHON_VENV="${OM_PYTHON_VENV:-$checkout_root/work/reference-python}"
    export OM_CACHE_ROOT="${OM_CACHE_ROOT:-$checkout_root/work/cache}"
    if [[ ! -x "$OM_GO_ROOT/bin/go" || ! -f "$OM_PYTHON_VENV/bin/activate" || ! -x "$OM_PYTHON_VENV/bin/python" ]]; then
        echo 'env.sh: selected Go toolchain or Python venv is absent; set OM_GO_ROOT and OM_PYTHON_VENV' >&2
        return 1
    fi
    source "$OM_PYTHON_VENV/bin/activate" || return 1
    export PATH="$OM_GO_ROOT/bin:$PATH"
    export GOTOOLCHAIN=local
    export GOCACHE="$OM_CACHE_ROOT/go-build"
    export GOMODCACHE="$OM_CACHE_ROOT/go-mod"
    export PRE_COMMIT_HOME="$OM_CACHE_ROOT/pre-commit"
    mkdir -p "$GOCACHE" "$GOMODCACHE" "$PRE_COMMIT_HOME" || return 1
    if [[ "$(go version)" != 'go version go1.27.2 '* || "$(python --version)" != 'Python 3.11.17' ]]; then
        echo 'env.sh: expected Go 1.27.2 and Python 3.11.17' >&2
        return 1
    fi
}
_om_env_init
_om_env_status=$?
unset -f _om_env_init
return "$_om_env_status" 2>/dev/null || exit "$_om_env_status"
