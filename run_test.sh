#!/bin/bash -xe

export CINDER_DIR=./cinder
export CINDER_REPO_URL=https://git.openstack.org/openstack/cinder
export INFORTREND_TEST_DIR=cinder/tests/unit/volume/drivers
export INFORTREND_DRIVER_DIR=cinder/volume/drivers/infortrend

if [ -d "$CINDER_DIR" ]; then
    rm -rf $CINDER_DIR
fi

git clone $CINDER_REPO_URL --depth=1

if [ ! -d "$CINDER_DIR/$INFORTREND_DRIVER_DIR" ]; then
    mkdir $CINDER_DIR/$INFORTREND_DRIVER_DIR
fi

if [ ! -d "$CINDER_DIR/$INFORTREND_TEST_DIR" ]; then
    mkdir $CINDER_DIR/$INFORTREND_TEST_DIR
fi

cp ./infortrend/* $CINDER_DIR/$INFORTREND_DRIVER_DIR/ -r
cp ./test/* $CINDER_DIR/$INFORTREND_TEST_DIR/ -r

sed -i '125 ifrom cinder.volume.drivers.infortrend.raidcmd_cli import common_cli as \\\n    cinder_volume_drivers_infortrend' ./cinder/cinder/opts.py
sed -i '305 i\\                cinder_volume_drivers_infortrend.infortrend_opts,' ./cinder/cinder/opts.py
echo '# Infortrend Driver' >> ./cinder/cinder/exception.py
echo 'class InfortrendCliException(CinderException):' >> ./cinder/cinder/exception.py
echo '    message = _("Infortrend CLI exception: %(err)s Param: %(param)s "' >> ./cinder/cinder/exception.py
echo '                "(Return Code: %(rc)s) (Output: %(out)s)")' >> ./cinder/cinder/exception.py

cd $CINDER_DIR

# tox -e ${1} test_infortrend_ -- --concurrency=8
# tox -e ${1} -- --concurrency=8
tox -e ${1} test_infortrend_

cd ..
