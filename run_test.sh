#!/bin/bash -xe

export CINDER_DIR=./cinder
export CINDER_REPO_URL="https://git.openstack.org/openstack/cinder"

echo "${CINDER_DIR}"
if [ -d "${CINDER_DIR}" ]; then
    rm -rf $CINDER_DIR
fi

git clone $CINDER_REPO_URL --depth=1 -b stable/newton

source setupIFTdriver.sh $CINDER_DIR

cd $CINDER_DIR

if [ $(grep "'{posargs}' --concurrency" -q "tox.ini") ]; then
    echo "Concurrency already set."
else
    # concurrency set to 4 for travisCI
    sed -i "s#stestr run '{posargs}'#stestr run '{posargs}' --concurrency=4#g" tox.ini
fi

tox -e ${1} test_infortrend_

cd ..
