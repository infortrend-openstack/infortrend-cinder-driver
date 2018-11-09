#!/bin/bash -xe

function test_flake8 {
    flake8 infortrend/
    flake8 test/infortrend/
}


function test_tox {
    export CINDER_DIR=./cinder
    export CINDER_REPO_URL="https://git.openstack.org/openstack/cinder"
    if [ -z "${2}" ]; then
        if [ -d "${CINDER_DIR}" ]; then
            echo "Deleting $CINDER_DIR"
            rm -rf $CINDER_DIR
        fi
        git clone $CINDER_REPO_URL --depth=1
    else
        echo "Skip Cloning cinder."
    fi

    source setupIFTdriver.sh $CINDER_DIR

    cd $CINDER_DIR

    # if grep "'{posargs}' --concurrency" -q "tox.ini"; then
    #     echo "Concurrency already set."
    # else
    #     echo "Setup concurrency=4 for travisCI.."
    #     sed -i "s#stestr run '{posargs}'#stestr run '{posargs}' --concurrency=4#g" tox.ini
    # fi

    tox -e ${1} test_infortrend_ -- --concurrency=4

    cd ..
}

if [ ${1} = "flake8" ]; then
    test_flake8
else
    test_tox "$@"
fi
