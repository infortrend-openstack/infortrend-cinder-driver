#!/bin/bash -xe

function test_flake8 {
    flake8 infortrend/
    flake8 test/infortrend/
}

function test_tox {
    export CINDER_DIR=/home/ift/cinder
    export CINDER_DIR=./cinder
    #export CINDER_REPO_URL="https://git.openstack.org/openstack/cinder"
    export CINDER_REPO_URL="https://github.com/openstack/cinder.git"

    if [ -z "${2}" ]; then
        if [ -d "${CINDER_DIR}" ]; then
            echo "Deleting $CINDER_DIR"
            rm -rf $CINDER_DIR
        fi
        git clone --branch juno-eol  $CINDER_REPO_URL --depth=1
    else
        echo "Skip Cloning cinder."
    fi

    source setupIFTdriver.sh $CINDER_DIR

    cd $CINDER_DIR

    if grep "python setup.py testr --slowest --testr-args='--concurrency 4 {posargs}'" -q "tox.ini"; then
        echo "Concurrency already set."
    else
        echo "Setup concurrency=4 for travisCI.."
        sed -i "s#python setup.py testr --slowest --testr-args='--concurrency 1 {posargs}'#python setup.py install#g" tox.ini
    fi

    if grep "psycopg2~=2.7" -q "test-requirements.txt"; then
        echo "psycopg2~=2.7 already set."
    else
        echo "Setup psycopg2~=2.7 for travisCI.."
        sed -i "s#psycopg2<=2.6#psycopg2~=2.7#g" test-requirements.txt
    fi

    tox -e ${1} test_infortrend_*
    cd ..
}

if [ ${1} = "flake8" ]; then
    test_flake8
else
    test_tox "$@"
fi