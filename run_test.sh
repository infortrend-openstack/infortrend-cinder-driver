#!/bin/bash -xe

export CINDER_DIR=./cinder
export CINDER_REPO_URL="https://git.openstack.org/openstack/cinder"
export INFORTREND_TEST_DIR="cinder/tests/unit/volume/drivers/infortrend"
export INFORTREND_DRIVER_DIR="cinder/volume/drivers/infortrend"

echo "Running Flake8..."
flake8 infortrend/
if [ $? -ne 0 ]; then
    exit 1
fi
flake8 test/infortrend/
if [ $? -ne 0 ]; then
    exit 1
fi
echo "Complete."

if [ -z "${2}" ]; then
    if [ -d "${CINDER_DIR}" ]; then
        echo "Deleting $CINDER_DIR"
        rm -rf $CINDER_DIR
    fi
    git clone $CINDER_REPO_URL --depth=1
else
    echo "Skip Cloning cinder."
fi

if [ ! -d "$CINDER_DIR/$INFORTREND_DRIVER_DIR" ]; then
    mkdir $CINDER_DIR/$INFORTREND_DRIVER_DIR
fi

if [ ! -d "$CINDER_DIR/$INFORTREND_TEST_DIR" ]; then
    mkdir $CINDER_DIR/$INFORTREND_TEST_DIR
fi

echo "Copy ./infortrend/*"
cp ./infortrend/* $CINDER_DIR/$INFORTREND_DRIVER_DIR/ -r
echo "Copy ./test/infortrend/*"
cp ./test/infortrend/* $CINDER_DIR/$INFORTREND_TEST_DIR/ -r

if grep "infortrend" -q "$CINDER_DIR/cinder/opts.py"; then
    echo "Driver opts already set."
else
    echo "Setup infortrend opts/exceptions.."
    source setupIFTdriver.sh
fi

sed -i '125 ifrom cinder.volume.drivers.infortrend.raidcmd_cli import common_cli as \\\n    cinder_volume_drivers_infortrend' ./cinder/cinder/opts.py
sed -i '305 i\\                cinder_volume_drivers_infortrend.infortrend_opts,' ./cinder/cinder/opts.py
echo '# Infortrend Driver' >> ./cinder/cinder/exception.py
echo 'class InfortrendCliException(CinderException):' >> ./cinder/cinder/exception.py
echo '    message = _("Infortrend CLI exception: %(err)s Param: %(param)s "' >> ./cinder/cinder/exception.py
echo '                "(Return Code: %(rc)s) (Output: %(out)s)")' >> ./cinder/cinder/exception.py

cd $CINDER_DIR

if grep "'{posargs}' --concurrency" -q "tox.ini"; then
    echo "Concurrency already set."
else
    echo "Setup concurrency=4 for travisCI.."
    sed -i "s#stestr run '{posargs}'#stestr run '{posargs}' --concurrency=4#g" tox.ini
fi

tox -e ${1} test_infortrend_

cd ..
