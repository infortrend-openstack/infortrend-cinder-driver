#!/bin/bash

#export INFORTREND_TEST_DIR="tests/unit/volume/drivers/infortrend"
export INFORTREND_TEST_DIR="tests/volume/drivers/infortrend"
export INFORTREND_DRIVER_DIR="volume/drivers/infortrend"

if [ -z "${1}" ]; then
    export BASE=/usr/lib/python2.7/dist-packages/cinder
else
	export BASE=${1}/cinder
fi

if [ ! -d "$BASE/$INFORTREND_DRIVER_DIR" ]; then
    pwd
    mkdir $BASE/$INFORTREND_DRIVER_DIR
fi

if [ ! -d "$BASE/$INFORTREND_TEST_DIR" ]; then
    pwd
    mkdir $BASE/$INFORTREND_TEST_DIR
fi

echo "Copying ./infortrend/* to $BASE/$INFORTREND_DRIVER_DIR/"
cp ./infortrend/* $BASE/$INFORTREND_DRIVER_DIR/ -r
echo "Copying ./test/infortrend/* to $BASE/$INFORTREND_TEST_DIR/"
cp ./test/infortrend/* $BASE/$INFORTREND_TEST_DIR/ -r

if grep "infortrend" -q "$BASE/opts.py"; then
    echo "Skip adding IFT opts/exceptions."
else
    # 131 & 325 will need to change as if opts.py/exceptions.py is updated
    echo "Setup infortrend opts/exceptions.."
   # sed -i '131 ifrom cinder.volume.drivers.infortrend.raidcmd_cli import common_cli as \\\n    cinder_volume_drivers_infortrend' $BASE/opts.py
   # sed -i '325 i\\                cinder_volume_drivers_infortrend.infortrend_opts,' $BASE/opts.py
    echo '# Infortrend Driver' >> $BASE/exception.py
    echo 'class InfortrendCliException(CinderException):' >> $BASE/exception.py
    echo '    message = _("Infortrend CLI exception: %(err)s Param: %(param)s "' >> $BASE/exception.py
    echo '                "(Return Code: %(rc)s) (Output: %(out)s)")' >> $BASE/exception.py
fi
