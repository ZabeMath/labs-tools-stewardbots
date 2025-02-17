#!/usr/bin/env bash
# Management script for <del>stashbot</del> StewardBot kubernetes processes
# https://github.com/wikimedia/stashbot/blob/master/bin/stashbot.sh

set -e

DEPLOYMENT=stewardbot
POD_NAME=stewardbot

TOOL_DIR=/data/project/stewardbots/stewardbots/StewardBot
VENV=/data/project/stewardbots/venv-k8s-py39
if [[ -f ${VENV}/bin/activate ]]; then
    # Enable virtualenv
    source ${VENV}/bin/activate
fi

KUBECTL=/usr/bin/kubectl

_get_pod() {
    $KUBECTL get pods \
        --output=jsonpath={.items..metadata.name} \
        --selector=name=${POD_NAME}
}

case "$1" in
    start)
        echo "Starting StewardBot k8s deployment..."
        $KUBECTL create --validate=true -f ${TOOL_DIR}/k8s-deployment.yaml
        ;;
    run)
        date +%Y-%m-%dT%H:%M:%S
        echo "Running StewardBot..."
        cd ${TOOL_DIR}
        exec python StewardBot.py
        ;;
    stop)
        echo "Stopping StewardBot k8s deployment..."
        $KUBECTL delete deployment ${DEPLOYMENT}
        # FIXME: wait for the pods to stop
        ;;
    restart)
        echo "Restarting StewardBot pod..."
        exec $KUBECTL delete pod $(_get_pod)
        ;;
    status)
        echo "Active pods:"
        exec $KUBECTL get pods -l name=${POD_NAME}
        ;;
    tail)
        exec $KUBECTL logs -f $(_get_pod)
        ;;
    attach)
        echo "Attaching to pod..."
        exec $KUBECTL exec -i -t $(_get_pod) -- /bin/bash
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|tail|attach}"
        exit 1
        ;;
esac

exit 0
# vim:ft=sh:sw=4:ts=4:sts=4:et:
