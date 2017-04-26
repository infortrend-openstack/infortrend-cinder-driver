#!/bin/bash -xe

export CINDER_DIR=./cinder
export CINDER_REPO_URL=https://git.openstack.org/openstack/cinder
export INFORTREND_TEST_DIR=cinder/tests/unit/
export INFORTREND_DRIVER_DIR=cinder/volume/drivers/infortrend

if [ -d "$CINDER_DIR" ]; then
    rm -rf $CINDER_DIR
fi

git clone -b stable/mitaka $CINDER_REPO_URL --depth=1

if [ ! -d "$CINDER_DIR/$INFORTREND_DRIVER_DIR" ]; then
    mkdir $CINDER_DIR/$INFORTREND_DRIVER_DIR
fi

if [ ! -d "$CINDER_DIR/$INFORTREND_TEST_DIR" ]; then
    mkdir $CINDER_DIR/$INFORTREND_TEST_DIR
fi

cp ./infortrend/* $CINDER_DIR/$INFORTREND_DRIVER_DIR/ -r
cp ./test/* $CINDER_DIR/$INFORTREND_TEST_DIR/ -r

cd $CINDER_DIR

tox -e ${1} test_infortrend_* -- --concurrency=4

cd ..
