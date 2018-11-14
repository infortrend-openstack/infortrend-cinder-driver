#!/bin/bash -xe

export CINDER_DIR=/home/ift/cinder
export CINDER_DIR=./cinder
#export CINDER_REPO_URL="https://git.openstack.org/openstack/cinder"
export CINDER_REPO_URL="https://github.com/openstack/cinder.git"
# echo "Running Flake8..."
# flake8 infortrend/
# if [ $? -ne 0 ]; then
#     exit 1
# fi
# flake8 test/infortrend/
# if [ $? -ne 0 ]; then
#     exit 1
# fi
# echo "Complete."

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

# if grep "'{posargs}' --concurrency" -q "tox.ini"; then
#     echo "Concurrency already set."
# else
#     echo "Setup concurrency=4 for travisCI.."
#     sed -i "s#stestr run '{posargs}'#stestr run '{posargs}' --concurrency=4#g" tox.ini
# fi

#tox -e ${1} test_infortrend_ -- --concurrency=4
tox -e ${1} test_infortrend_cli -- --concurrency=4
tox -e ${1} test_infortrend_common -- --concurrency=4

cd ..
