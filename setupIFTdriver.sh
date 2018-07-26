#!/bin/bash

export BASE=./cinder/cinder/

sed -i '131 ifrom cinder.volume.drivers.infortrend.raidcmd_cli import common_cli as \\\n    cinder_volume_drivers_infortrend' $BASE/opts.py
sed -i '325 i\\                cinder_volume_drivers_infortrend.infortrend_opts,' $BASE/opts.py
echo '# Infortrend Driver' >> $BASE/exception.py
echo 'class InfortrendCliException(CinderException):' >> $BASE/exception.py
echo '    message = _("Infortrend CLI exception: %(err)s Param: %(param)s "' >> $BASE/exception.py
echo '                "(Return Code: %(rc)s) (Output: %(out)s)")' >> $BASE/exception.py
