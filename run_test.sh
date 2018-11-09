#!/bin/bash -xe

export CINDER_DIR=./cinder
export CINDER_REPO_URL="https://git.openstack.org/openstack/cinder"

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
    git clone -b driverfixes/mitaka $CINDER_REPO_URL --depth=1
else
    echo "Skip Cloning cinder."
fi

source setupIFTdriver.sh $CINDER_DIR

cd $CINDER_DIR

tox -e ${1} -- -n cinder.tests.unit.volume.drivers.infortrend.test_infortrend_common --concurrency=4

cd ..
